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
//   REBUILD_HISTORY (optional) "true" lädt alle vergangenen Saisons neu ins Archiv

import { readFile, writeFile, mkdir } from "node:fs/promises";

const API = process.env.CLUBEE_API || "https://apiv3.clubee.com"; // CLUBEE_API nur für lokale Tests
const TOKEN = process.env.CLUBEE_TOKEN;
const WEBSITE = process.env.CLUBEE_WEBSITE || "afbo";
const COMPETITION_ID = Number(process.env.COMPETITION_ID || 13931);
const SEASON_ID = Number(process.env.SEASON_ID || 217);
const FORCE = process.env.FORCE === "true";
const OUT_FILE = "data/afl.json";
const HISTORY_DIR = "data/history";       // Archiv je Saison (nur IDs und Zahlen)
const CAREER_FILE = "data/career.json";   // Karrierewerte für die Spieler-Detailansicht
const REBUILD_HISTORY = process.env.REBUILD_HISTORY === "true";
// Anzahl der Grunddurchgangsspiele pro Team. Jedes weitere Spiel eines Teams gilt als Playoff-Spiel.
const REGULAR_GAMES = Number(process.env.REGULAR_GAMES || 10);

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

function statColumns(header, rows) {
  const keys = new Set();
  for (const r of rows) for (const k of Object.keys(r.stats || {})) keys.add(k);
  const entries = Object.entries(header || {}).filter(([k]) => keys.size === 0 || keys.has(k));
  const cols = entries.map(([key, h]) => ({
    key,
    label: typeof h === "string" ? h : (h?.translate_acronym || h?.short || h?.abbreviation || h?.translate || h?.label || h?.name || key),
    title: typeof h === "object" && h ? (h.translate_name || h.translate || h.label || "") : ""
  }));
  for (const k of keys) if (!cols.some(c => c.key === k)) cols.push({ key: k, label: k, title: "" });
  return cols;
}

function statValue(v) {
  if (v && typeof v === "object") v = v.value ?? v.total ?? null;
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

// Eine Statistik-Kategorie (Spieler oder Teams) komplett holen – nur Name, IDs und Zahlen
async function fetchStatCategory(cat, kind, seasonId = SEASON_ID) {
  const limit = 200;
  let header = null;
  const raw = [];
  for (let offset = 0; offset < 5000; offset += limit) {
    const page = await api(`/competitions/${COMPETITION_ID}/seasons/${seasonId}/stats/categories/${cat.id}/${kind}?_limit=${limit}&_offset=${offset}`);
    header = header || page?.header;
    const rows = page?.rows || [];
    raw.push(...rows);
    if (rows.length < limit || raw.length >= (page?.total ?? 0)) break;
  }
  const columns = statColumns(header, raw);
  const rows = raw.map(r => {
    const values = columns.map(c => statValue(r.stats?.[c.key]));
    if (kind === "players") {
      const u = r.user || {};
      return {
        user_id: u.id ?? null,
        name: `${u.firstname || ""} ${u.lastname || ""}`.trim(),
        team_id: r.group?.id ?? null,
        values
      };
    }
    return { team_id: r.group?.id ?? null, name: r.group?.name || "", values };
  }).filter(r => r.name && r.values.some(v => v !== null && v !== 0));
  return { id: cat.id, name: cat.name || `Kategorie ${cat.id}`, columns: columns.map(({ key, ...c }) => c), rows };
}

// Alle Spiele einer Saison holen. Ohne _date liefert Clubee nur Spiele ab heute –
// deshalb ausdrücklich ab 2000 abfragen und bei vielen Spielen seitenweise nachladen.
async function fetchScenes(seasonId) {
  const limit = 200;
  const byId = new Map();
  let cursor = "2000-01-01T00:00:00Z";
  for (let page = 0; page < 25; page++) {
    const rows = await api(`/competitions/${COMPETITION_ID}/seasons/${seasonId}/scenes?_date=${encodeURIComponent(cursor)}&_limit=${limit}`);
    const list = Array.isArray(rows) ? rows : (rows?.data || []);
    let added = 0;
    for (const g of list) if (g && g.id != null && !byId.has(g.id)) { byId.set(g.id, g); added++; }
    if (list.length < limit || added === 0) break;
    const last = list.map(g => g.start_date).filter(Boolean).sort().pop();
    if (!last || last === cursor) break;
    cursor = last;
  }
  return [...byId.values()];
}

// Welche Spiele sind Playoff-Spiele? Drei Regeln, jede reicht für sich:
// 1. Das Spiel liegt in einer anderen Clubee-Phase als die meisten Spiele (die größte Phase = Grunddurchgang).
// 2. Phase oder Runde heißen z. B. "Playoffs", "Wild Card", "Halbfinale", "Austrian Bowl".
// 3. Eines der beiden Teams hat bereits REGULAR_GAMES Grunddurchgangsspiele (chronologisch gezählt).
function playoffIds(scenes) {
  const RE = /playoff|play-off|wild ?card|semi|halb|viertel|quarter|finale?\b|bowl|k\.?\s?o\.?-runde/i;
  const valid = (scenes || []).filter(g => g && !g.cancelled);
  const set = new Set();
  const phaseKey = g => g.phase?.id ?? g.phase?.name ?? null;
  const byPhase = new Map();
  valid.forEach(g => { const k = phaseKey(g); if (k !== null) byPhase.set(k, (byPhase.get(k) || 0) + 1); });
  const mainPhase = byPhase.size > 1 ? [...byPhase.entries()].sort((a, b) => b[1] - a[1])[0][0] : null;
  valid.forEach(g => {
    if (mainPhase !== null && phaseKey(g) !== mainPhase) set.add(g.id);
    else if (RE.test(`${g.phase?.name || ""} ${g.round?.name || ""}`) && !(mainPhase !== null && phaseKey(g) === mainPhase)) set.add(g.id);
  });
  if (REGULAR_GAMES > 0) {
    const count = new Map();
    [...valid].sort((a, b) => String(a.start_date).localeCompare(String(b.start_date))).forEach(g => {
      if (set.has(g.id)) return;
      const a = g.team1?.id, b = g.team2?.id;
      if ((count.get(a) || 0) >= REGULAR_GAMES || (count.get(b) || 0) >= REGULAR_GAMES) { set.add(g.id); return; }
      count.set(a, (count.get(a) || 0) + 1); count.set(b, (count.get(b) || 0) + 1);
    });
  }
  return set;
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

// Kicking und Punting – berechnet aus Box Score und Spielprotokoll jedes gespielten Spiels.
  // Clubee hat für die AFL keine eigenen Kategorien dafür.
  // FG-Distanz = Ballposition (Feld "distance" beim FG-Versuch) + 17 Yards (Endzone + Holder).
  // Punt-Weiten werden nicht erfasst und deshalb nicht berechnet.
async function computeKickingPunting(seasonId) {
  try {
    const scenes = await fetchScenes(seasonId);
    const kick = new Map();   // user_id -> Kicker-Werte
    const punt = new Map();   // user_id -> Punter-Werte
    const typeOf = x => String(x?.scene_action_type?.translate || "").trim().toLowerCase();
    const personName = u => `${u?.first_name || u?.firstname || ""} ${u?.last_name || u?.lastname || ""}`.trim();
    const kicker = (uid, name, team) => {
      if (!kick.has(uid)) kick.set(uid, { user_id: uid, name, team_id: team, games: new Set(), fgm: 0, fga: 0, lng: null, xpp: 0, xpm: 0 });
      const e = kick.get(uid); if (!e.name && name) e.name = name; if (!e.team_id && team) e.team_id = team; return e;
    };
    const punter = (uid, name, team) => {
      if (!punt.has(uid)) punt.set(uid, { user_id: uid, name, team_id: team, games: new Set(), n: 0, blk: 0, oob: 0, ret: 0, fc: 0, tb: 0 });
      const e = punt.get(uid); if (!e.name && name) e.name = name; if (!e.team_id && team) e.team_id = team; return e;
    };
    let boxCount = 0, pbpCount = 0;

    for (const g of scenes || []) {
      if (!g.completed || g.cancelled) continue;

      // 1) Spielprotokoll: Field-Goal-Versuche und Punts
      let pbpHasFG = false;
      try {
        const summary = await api(`/matches/${g.id}/summary`);
        const plays = [];
        const walk = x => { if (Array.isArray(x)) x.forEach(walk); else if (x && typeof x === "object" && x.scene_action_type) plays.push(x); };
        walk(summary);
        for (const play of plays) {
          const kids = play.children || [];
          // Field Goal
          if (typeOf(play) === "field goal try" && play.user1?.id) {
            pbpHasFG = true;
            const e = kicker(play.user1.id, personName(play.user1), play.group?.id ?? null);
            e.games.add(g.id); e.fga++;
            if (kids.some(k => typeOf(k) === "field goal good")) {
              e.fgm++;
              const spot = Number(play.distance);
              if (Number.isFinite(spot) && spot >= 0 && spot <= 60) e.lng = Math.max(e.lng ?? 0, spot + 17);
            }
          }
          // Punt (als Unterspielzug eines Scrimmage-Spielzugs)
          const pk = kids.find(k => typeOf(k) === "punt");
          if (pk && pk.user1?.id) {
            const e = punter(pk.user1.id, personName(pk.user1), pk.group?.id ?? play.group?.id ?? null);
            e.games.add(g.id); e.n++;
            const t = kids.map(typeOf);
            if (t.includes("blocked")) e.blk++;
            if (t.includes("kick out of bounds")) e.oob++;
            if (t.includes("punt return")) e.ret++;
            if (t.includes("fair catch")) e.fc++;
            if (t.includes("touchback")) e.tb++;
          }
        }
        pbpCount++;
      } catch (e) {
        console.warn(`Spielprotokoll Spiel ${g.id}: ${e.message}`);
      }

      // 2) Box Score: Extra Points (und FG, falls das Protokoll keine FG enthält)
      try {
        const box = await api(`/scenes/${g.id}/stats`);
        const h = box?.header || {};
        const keyOf = ac => Object.keys(h).find(k => h[k]?.acronym === ac);
        const kFG = keyOf("fg_acronym"), kXPp = keyOf("xp_plus_acronym"), kXPm = keyOf("xp_minus_acronym");
        for (const r of box?.rows || []) {
          const uid = r.user?.id ?? null;
          if (!uid) continue;
          const fg = Number(r[kFG]) || 0, xpp = Number(r[kXPp]) || 0, xpm = Number(r[kXPm]) || 0;
          if (!xpp && !xpm && !(fg && !pbpHasFG)) continue;
          // Nur Name, Team und Zahlen – Box Score enthält auch Lizenz- und Medizinangaben
          const e = kicker(uid, personName(r), r.group_id ?? null);
          e.games.add(g.id); e.xpp += xpp; e.xpm += xpm;
          if (fg && !pbpHasFG) { e.fgm += fg; e.fga += fg; }
        }
        boxCount++;
      } catch (e) {
        console.warn(`Box Score Spiel ${g.id}: ${e.message}`);
      }
      await sleep(150);
    }

    const pct = (a, b) => (b ? Math.round((a / b) * 1000) / 10 : null);
    const kickRows = [...kick.values()].filter(e => e.name).map(e => ({
      user_id: e.user_id, name: e.name, team_id: e.team_id,
      values: [e.games.size, e.fgm, e.fga, pct(e.fgm, e.fga), e.lng, e.xpp, e.xpm, pct(e.xpp, e.xpp + e.xpm), e.fgm * 3 + e.xpp]
    })).sort((a, b) => b.values[8] - a.values[8] || b.values[1] - a.values[1]);
    const puntRows = [...punt.values()].filter(e => e.name).map(e => ({
      user_id: e.user_id, name: e.name, team_id: e.team_id,
      values: [e.games.size, e.n, e.blk, e.oob, e.ret, e.fc, e.tb]
    })).sort((a, b) => b.values[1] - a.values[1]);

    const blocks = [];
    if (kickRows.length) blocks.push({
      id: "kicking", name: "Kicking", computed: true,
      columns: [
        { label: "SP", title: "Spiele mit Kick" },
        { label: "FG", title: "Field Goals verwandelt" },
        { label: "FGV", title: "Field-Goal-Versuche" },
        { label: "FG %", title: "Field-Goal-Quote" },
        { label: "LNG", title: "Längstes Field Goal (Yards, berechnet)" },
        { label: "XP+", title: "Extra Points verwandelt" },
        { label: "XP-", title: "Extra Points verschossen" },
        { label: "XP %", title: "Extra-Point-Quote" },
        { label: "PKT", title: "Punkte durch Kicks (FG × 3 + XP)" }
      ],
      rows: kickRows
    });
    if (puntRows.length) blocks.push({
      id: "punting", name: "Punting", computed: true,
      columns: [
        { label: "SP", title: "Spiele mit Punt" },
        { label: "PUNTS", title: "Punts" },
        { label: "GEBL", title: "Geblockt" },
        { label: "AUS", title: "Ins Aus" },
        { label: "RET", title: "Mit Return" },
        { label: "FC", title: "Fair Catch" },
        { label: "TB", title: "Touchback" }
      ],
      rows: puntRows
    });
    console.log(`Kicking/Punting ${seasonId}: ${pbpCount} Protokolle, ${boxCount} Box Scores, ${kickRows.length} Kicker, ${puntRows.length} Punter`);
    return blocks;
  } catch (e) {
    console.warn(`Kicking/Punting ${seasonId} nicht berechenbar: ${e.message}`);
    return [];
  }
}

// Alle Kategorie-Statistiken einer Saison
async function fetchSeasonCategoryStats(seasonId, cats, kinds) {
  const out = { players: [], teams: [] };
  for (const cat of cats) {
    for (const kind of kinds) {
      const t = String(cat.type || "");
      if (kind === "players" && /team/i.test(t)) continue;
      if (kind === "teams" && /player|user/i.test(t)) continue;
      if (kind === "teams" && /^standings$/i.test(String(cat.name || "").trim())) continue; // doppelt zur eigenen Tabelle
      try {
        const block = await fetchStatCategory(cat, kind, seasonId);
        if (block.rows.length) out[kind].push(block);
      } catch (e) {
        console.warn(`Statistik ${cat.name} (${kind}, Saison ${seasonId}) nicht abrufbar: ${e.message}`);
      }
      await sleep(150);
    }
  }
  return out;
}

// Für Archiv und Karriere nur IDs und Zahlen speichern (keine Namen)
function slimBlocks(blocks) {
  return blocks.map(b => ({
    name: b.name,
    columns: b.columns,
    rows: b.rows.filter(r => r.user_id != null).map(r => ({ user_id: r.user_id, values: r.values }))
  }));
}

// Karriere aufbauen: vergangene Saisons aus dem Archiv (fehlende einmalig nachladen) + aktuelle Saison
async function buildCareer(statCats, currentBlocks, seasons, currentName) {
  await mkdir(HISTORY_DIR, { recursive: true });
  const nameOf = id => seasons.find(x => x.id === id)?.name || String(id);

  let ids = [];
  try {
    const list = await api(`/competitions/${COMPETITION_ID}/seasonshavingplayerstats`);
    ids = (Array.isArray(list) ? list : list?.data || []).map(x => (x && typeof x === "object" ? x.id : x)).map(Number);
  } catch (e) {
    console.warn(`Saisons mit Statistiken nicht abrufbar: ${e.message}`);
  }
  // Nur Saisons vor der aktuellen (IDs steigen mit den Jahren)
  const pastIds = [...new Set(ids)].filter(id => Number.isFinite(id) && id < SEASON_ID).sort((a, b) => a - b);

  const seasonData = [];
  for (const id of pastIds) {
    const file = `${HISTORY_DIR}/season-${id}.json`;
    let data = null;
    if (!REBUILD_HISTORY) {
      try { data = JSON.parse(await readFile(file, "utf8")); } catch { /* noch nicht im Archiv */ }
    }
    if (!data) {
      console.log(`Archiv: lade Saison ${nameOf(id)} …`);
      const blocks = (await fetchSeasonCategoryStats(id, statCats, ["players"])).players;
      blocks.push(...await computeKickingPunting(id));
      data = { season: { id, name: nameOf(id) }, updated_at: new Date().toISOString(), players: slimBlocks(blocks) };
      await writeFile(file, JSON.stringify(data) + "\n", "utf8");
    }
    seasonData.push(data);
  }

  // Aktuelle Saison ebenfalls archivieren (wird nach dem Saisonwechsel zur abgeschlossenen Saison)
  const current = { season: { id: SEASON_ID, name: currentName }, updated_at: new Date().toISOString(), players: slimBlocks(currentBlocks) };
  await writeFile(`${HISTORY_DIR}/season-${SEASON_ID}.json`, JSON.stringify(current) + "\n", "utf8");
  seasonData.push(current);

  const all = seasonData.filter(d => d.players?.length)
    .sort((a, b) => String(a.season.name).localeCompare(String(b.season.name), "de", { numeric: true }));
  const career = { updated_at: new Date().toISOString(), seasons: all.map(d => d.season.name), categories: [], columns: {}, titles: {}, players: {} };
  for (const b of currentBlocks) if (!career.categories.includes(b.name)) career.categories.push(b.name);
  for (const d of all) {
    for (const b of d.players) {
      if (!career.categories.includes(b.name)) career.categories.push(b.name);
      (career.columns[b.name] ||= {})[d.season.name] = b.columns.map(c => c.label);
      const titles = (career.titles[b.name] ||= {});
      for (const c of b.columns) if (c.title && !titles[c.label]) titles[c.label] = c.title;
      for (const r of b.rows) {
        const perSeason = ((career.players[r.user_id] ||= {})[d.season.name] ||= {});
        perSeason[b.name] = r.values;
      }
    }
  }
  await writeFile(CAREER_FILE, JSON.stringify(career) + "\n", "utf8");
  console.log(`Karriere: ${career.seasons.length} Saisons (${career.seasons.join(", ")}), ${Object.keys(career.players).length} Spieler`);
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

  // Bilanz (Siege/Niederlagen) aus den gespielten Spielen des Grunddurchgangs
  let records = null;
  try {
    const scenes = await fetchScenes(SEASON_ID);
    const po = playoffIds(scenes);
    const rec = new Map(outTeams.map(t => [t.id, { team_id: t.id, w: 0, l: 0, t: 0, pf: 0, pa: 0 }]));
    const results = new Map(outTeams.map(t => [t.id, []])); // für die aktuelle Serie
    const games = [...(scenes || [])].sort((x, y) => String(x.start_date).localeCompare(String(y.start_date)));
    for (const g of games) {
      if (!g.completed || g.cancelled) continue;
      if (po.has(g.id)) continue; // nur Grunddurchgang zählt für die Tabelle
      const a = rec.get(g.team1?.id), b = rec.get(g.team2?.id);
      const s1 = Number(g.score1), s2 = Number(g.score2);
      if (!a || !b || !Number.isFinite(s1) || !Number.isFinite(s2)) continue;
      a.pf += s1; a.pa += s2; b.pf += s2; b.pa += s1;
      if (s1 > s2) { a.w++; b.l++; } else if (s2 > s1) { b.w++; a.l++; } else { a.t++; b.t++; }
      results.get(a.team_id).push(s1 > s2 ? "S" : s1 < s2 ? "N" : "U");
      results.get(b.team_id).push(s2 > s1 ? "S" : s2 < s1 ? "N" : "U");
    }
    for (const r of rec.values()) {
      const list = results.get(r.team_id);
      let n = 0;
      for (let i = list.length - 1; i >= 0 && list[i] === list[list.length - 1]; i--) n++;
      r.streak = n ? `${n}${list[list.length - 1]}` : null;
    }
    const pct = r => (r.w + r.l + r.t) ? (r.w + r.t / 2) / (r.w + r.l + r.t) : 0;
    records = [...rec.values()].sort((x, y) =>
      pct(y) - pct(x) || y.w - x.w || (y.pf - y.pa) - (x.pf - x.pa) || y.pf - x.pf);
  } catch (e) {
    console.warn(`Spiele nicht abrufbar: ${e.message}`);
  }

  // Spielplan (für Spielplan, Playoffs, Strength of Schedule und Teamseiten)
  // Annahme: team1 = Heimteam, team2 = Gastteam (so wie Clubee Spiele anzeigt)
  let games = [];
  try {
    const scenes = await fetchScenes(SEASON_ID);
    const po = playoffIds(scenes);
    const num = v => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v))) ? null : Number(v);
    games = (scenes || []).map(g => ({
      id: g.id,
      date: g.start_date || null,
      home_id: g.team1?.id ?? null,
      home: g.team1?.name || "",
      away_id: g.team2?.id ?? null,
      away: g.team2?.name || "",
      home_score: g.completed ? num(g.score1) : null,
      away_score: g.completed ? num(g.score2) : null,
      completed: g.completed === true,
      cancelled: g.cancelled === true,
      phase: String(g.phase?.name || ""),
      playoff: po.has(g.id),
      round: String(g.round?.name || g.game_day || ""),
      venue: g.venue_name || "",
      city: g.venue_city || "",
      stream: typeof g.stream_link === "string" && /^https:\/\//.test(g.stream_link) ? g.stream_link : null
    })).sort((a, b) => String(a.date).localeCompare(String(b.date)));
    const phases = [...new Set((scenes || []).map(g => g.phase?.name).filter(Boolean))];
    console.log(`Spielplan: ${games.length} Spiele – Grunddurchgang ${games.filter(g => !g.playoff && !g.cancelled).length}, Playoffs ${games.filter(g => g.playoff).length}` +
      (phases.length ? ` (Phasen in Clubee: ${phases.join(", ")})` : ""));
  } catch (e) {
    console.warn(`Spielplan nicht abrufbar: ${e.message}`);
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

  // Spieler- und Teamstatistiken der aktuellen Saison
  let statCats = [];
  try {
    statCats = (await api(`/competitions/${COMPETITION_ID}/stats/categories`) || [])
      .sort((x, y) => (x.position ?? 0) - (y.position ?? 0));
  } catch (e) {
    console.warn(`Statistik-Kategorien nicht abrufbar: ${e.message}`);
  }
  const stats = await fetchSeasonCategoryStats(SEASON_ID, statCats, ["players", "teams"]);
  stats.players.push(...await computeKickingPunting(SEASON_ID));
  console.log(`Statistiken: ${stats.players.length} Spieler-Kategorien, ${stats.teams.length} Team-Kategorien`);

  // Karriere über alle Saisons (Archiv + aktuelle Saison)
  try {
    await buildCareer(statCats, stats.players, seasons, season?.name || String(seasonYear));
  } catch (e) {
    console.warn(`Karriere nicht erstellt: ${e.message}`);
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
    records,
    games,
    standings,
    stats
  };

  await mkdir("data", { recursive: true });
  await writeFile(OUT_FILE, JSON.stringify(output, null, 1) + "\n", "utf8");
  console.log(`Fertig: ${outTeams.length} Teams, ${outPlayers.length} Spieler, ${outStaff.length} Staff.`);
}

main().catch(err => {
  console.error("Sync fehlgeschlagen:", err.message);
  process.exit(1);
});
