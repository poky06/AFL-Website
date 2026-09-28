// AFL-Website: Clubee-Sync
// Holt Teams, Kader, Lizenzklassen und Tabelle aus der Clubee-API und schreibt
// eine bereinigte Datei data/afl.json. Es werden NUR die unten erlaubten Felder
// übernommen – Adressen, Telefonnummern, E-Mails, Dokumente usw. werden verworfen.
//
// Umgebungsvariablen:
//   CLUBEE_TOKEN    (Pflicht)  API-Key – nur als GitHub-Secret, nie im Code
//   CLUBEE_WEBSITE  (optional) Standard: afbo
//   COMPETITION_ID  (optional) Standard: 13931 (AFL)
//   SEASON_ID       (optional) Standard: 217 (2026) – für 2027: 219
//   FORCE           (optional) "true" überspringt die Plausibilitätsprüfung

import { readFile, writeFile, mkdir } from "node:fs/promises";

const API = process.env.CLUBEE_API || "https://apiv3.clubee.com"; // CLUBEE_API nur für lokale Tests
const TOKEN = process.env.CLUBEE_TOKEN;
const WEBSITE = process.env.CLUBEE_WEBSITE || "afbo";
const COMPETITION_ID = Number(process.env.COMPETITION_ID || 13931);
const SEASON_ID = Number(process.env.SEASON_ID || 217);
const FORCE = process.env.FORCE === "true";
const OUT_FILE = "data/afl.json";

if (!TOKEN) {
  console.error("Fehler: CLUBEE_TOKEN ist nicht gesetzt.");
  process.exit(1);
}

// Positions-Kürzel (IDs aus /sports/11/positions)
const POSITION_ABBR = {
  60: "WR", 61: "OT", 62: "OG", 63: "C", 64: "TE", 65: "QB", 66: "FB", 67: "HB",
  68: "CB", 69: "DE", 70: "DT", 71: "OLB", 72: "MLB", 73: "FS", 74: "SS", 75: "K",
  76: "LB", 77: "RB", 78: "DB", 79: "P", 80: "LS", 81: "GUN", 82: "NT", 83: "OL",
  84: "T", 100: "ATH", 268: "DL"
};

// Lesbare Namen für bekannte Staff-Rollen; unbekannte werden "Trainerstab"
const STAFF_ROLE = {
  coaches: "Coach",
  team_carer: "Betreuer",
  director: "Manager",
  position_staff_second_assistant_coach: "Assistant Coach",
  position_staff_third_assistant_coach: "Assistant Coach",
  position_staff_phisical_trainer: "Athletiktrainer",
  position_staff_phisiotherapist: "Physiotherapeut",
  position_staff_doctor: "Teamarzt",
  position_staff_medical_staff: "Medical Staff",
  position_staff_team_delegate: "Teamdelegierter"
};

// Nur Bild-URLs als Foto zulassen (Schutz davor, dass ein Dokument-Link durchrutscht)
const IMAGE_URL = /^https:\/\/[^\s]+\.(jpe?g|png|webp)$/i;

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function api(path, { retries = 3 } = {}) {
  for (let attempt = 1; attempt <= retries; attempt++) {
    const res = await fetch(API + path, {
      headers: { "X-Api-Token": TOKEN, "x-website": WEBSITE, Accept: "application/json" }
    });
    if (res.ok) return res.json();
    // Keine Antwortinhalte loggen – sie könnten Personendaten enthalten
    const msg = `HTTP ${res.status} bei ${path.split("?")[0]}`;
    if (res.status === 429 || res.status >= 500) {
      if (attempt < retries) { await sleep(2000 * attempt); continue; }
    }
    throw new Error(msg);
  }
}

function normalizeLicenseClass(name) {
  if (!name) return null;
  const n = name.trim().toLowerCase();
  if (n === "homegrown") return "Homegrown";
  if (n === "a klasse" || n === "a-klasse") return "A-Klasse";
  if (n === "e klasse" || n === "e-klasse") return "E-Klasse";
  if (n === "oe klasse" || n === "oe-klasse") return "OE-Klasse";
  return name.trim();
}

function isoDate(value) {
  if (!value) return null;
  const d = String(value).slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(d) ? d : null;
}

function pickLicenseClass(licenses, seasonYear, optionNames) {
  if (!Array.isArray(licenses)) return null;
  const seasonStart = `${seasonYear}-01-01`;
  const seasonEnd = `${seasonYear}-12-31`;
  const valid = licenses
    .filter(l => l.status === "approved")
    .filter(l => {
      const start = isoDate(l.start_date || l.start) || "0000-01-01";
      const end = isoDate(l.end_date || l.expiration) || "9999-12-31";
      return start <= seasonEnd && end >= seasonStart;
    })
    .sort((a, b) => String(b.start_date).localeCompare(String(a.start_date)));
  for (const l of valid) {
    const optId = l.options?.[0]?.option?.id;
    if (optId && optionNames.has(optId)) return normalizeLicenseClass(optionNames.get(optId));
  }
  return null;
}

async function fetchMembers(groupId) {
  const members = [];
  const limit = 100;
  for (let offset = 0; offset < 2000; offset += limit) {
    const page = await api(`/group/${groupId}/season/${SEASON_ID}/users?_limit=${limit}&_offset=${offset}`);
    const rows = page?.data || [];
    members.push(...rows);
    const total = page?._meta?.total ?? rows.length;
    if (rows.length < limit || members.length >= total) break;
  }
  return members;
}

async function main() {
  console.log(`Sync startet: Wettbewerb ${COMPETITION_ID}, Saison ${SEASON_ID}`);

  const [countries, positionsBySport, packages, seasons, teams] = await Promise.all([
    api("/countries"),
    api("/sports/11/positions"),
    api("/licenses/packages"),
    api(`/competitions/${COMPETITION_ID}/seasons`),
    api(`/competitions/${COMPETITION_ID}/seasons/${SEASON_ID}/teams`)
  ]);

  const countryIoc = new Map(countries.filter(c => c.ioc && c.ioc !== "NULL").map(c => [c.id, c.ioc]));
  const playerPosIds = new Set((positionsBySport.player || []).map(p => p.id));
  const staffPosName = new Map((positionsBySport.staff || []).map(p => [p.id, p.name]));
  const optionNames = new Map();
  for (const pkg of packages) for (const o of pkg.options || []) optionNames.set(o.id, o.name);

  const season = seasons.find(s => s.id === SEASON_ID);
  const seasonYear = Number(season?.name) || new Date().getFullYear();

  const outTeams = [];
  const outPlayers = [];
  const outStaff = [];

  for (const team of teams) {
    outTeams.push({
      id: team.id,
      name: team.name,
      logo: IMAGE_URL.test(team.pic_s || "") ? team.pic_s : null,
      logo_big: IMAGE_URL.test(team.pic_b || "") ? team.pic_b : null
    });

    const members = await fetchMembers(team.id);
    let shown = 0;

    for (const m of members) {
      if (m.display_on_website !== true) continue;
      shown++;

      const posIds = Array.isArray(m.positions) ? m.positions : [];
      const playerPositions = posIds.filter(id => playerPosIds.has(id)).map(id => POSITION_ABBR[id] || "?");
      const staffRoles = posIds.filter(id => staffPosName.has(id)).map(id => STAFF_ROLE[staffPosName.get(id)] || "Trainerstab");
      const isStaff = staffRoles.length > 0 && playerPositions.length === 0;

      // Ausschließlich diese Felder verlassen das Skript:
      const base = {
        id: m.id,
        team_id: team.id,
        firstname: m.firstname || "",
        lastname: m.lastname || "",
        birthday: isoDate(m.birthday),
        nationality: countryIoc.get(m.nationality?.id) || null,
        photo: IMAGE_URL.test(m.pic_roster || m.picture || "") ? (m.pic_roster || m.picture) : null
      };

      if (isStaff) {
        outStaff.push({ ...base, role: [...new Set(staffRoles)].join(" / ") });
      } else {
        let license = null;
        try {
          license = pickLicenseClass(await api(`/licenses/users/${m.id}`), seasonYear, optionNames);
        } catch (e) {
          console.warn(`Lizenz nicht abrufbar (Spieler-ID ${m.id}): ${e.message}`);
        }
        outPlayers.push({
          ...base,
          jersey_number: Number.isInteger(m.jersey_number) ? m.jersey_number : null,
          positions: [...new Set(playerPositions)],
          license
        });
        await sleep(150); // API schonen
      }
    }
    console.log(`${team.name}: ${members.length} Mitglieder, ${shown} für die Website freigegeben`);
  }

  // Tabelle (falls vorhanden)
  let standings = null;
  try {
    const raw = await api(`/competitions/${COMPETITION_ID}/seasons/${SEASON_ID}/standings`);
    standings = (raw || []).map(phase => {
      const header = Array.isArray(phase.header) ? phase.header : Object.values(phase.header || {});
      return {
        phase: phase.phase?.name || "",
        columns: header.map(h => (typeof h === "string" ? h : h?.translate || h?.name || h?.label || "")),
        rows: (phase.rows || []).map(r => ({
          team_id: r.group?.id ?? null,
          team: r.group?.name || "",
          stats: Object.keys(r)
            .filter(k => /^stat\d+$/.test(k))
            .sort((a, b) => Number(a.slice(4)) - Number(b.slice(4)))
            .map(k => r[k])
            .filter(v => v !== null && v !== undefined)
        }))
      };
    });
  } catch (e) {
    console.warn(`Tabelle nicht abrufbar: ${e.message}`);
  }

  // Plausibilitätsprüfung: Bei API-Störung nicht die Website leeren
  if (outPlayers.length === 0) throw new Error("Keine Spieler erhalten – Datei wird nicht überschrieben.");
  try {
    const prev = JSON.parse(await readFile(OUT_FILE, "utf8"));
    const before = prev.players?.length || 0;
    if (!FORCE && before > 0 && outPlayers.length < before * 0.5) {
      throw new Error(`Spielerzahl von ${before} auf ${outPlayers.length} gefallen – abgebrochen. Mit FORCE=true erzwingen.`);
    }
  } catch (e) {
    if (e.code !== "ENOENT" && !(e instanceof SyntaxError)) throw e;
  }

  const output = {
    updated_at: new Date().toISOString(),
    competition_id: COMPETITION_ID,
    season: { id: SEASON_ID, name: season?.name || String(seasonYear) },
    teams: outTeams,
    players: outPlayers,
    staff: outStaff,
    standings
  };

  await mkdir("data", { recursive: true });
  await writeFile(OUT_FILE, JSON.stringify(output, null, 1) + "\n", "utf8");
  console.log(`Fertig: ${outTeams.length} Teams, ${outPlayers.length} Spieler, ${outStaff.length} Staff.`);
}

main().catch(err => {
  console.error("Sync fehlgeschlagen:", err.message);
  process.exit(1);
});
