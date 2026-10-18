import { html, render, useEffect, useMemo, useState } from "./vendor/preact-htm.js";
import { CIV_ICON, GROUP_COLORS, colorName, colorOf, pct, useLiveState } from "./common.js";

const games = (n) => `${n} game${n === 1 ? "" : "s"}`;
const PROFILE_URL = (id) => `https://www.aoe2companion.com/profile/${id}`;

function currentHash() {
  return (window.location.hash || "#/").replace(/^#\/?/, "") || "/";
}

function App() {
  const [state, connected] = useLiveState();
  const [picking, setPicking] = useState(false);
  const [route, setRoute] = useState(currentHash);
  useEffect(() => {
    const onHash = () => setRoute(currentHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  if (!state) return html`<div class="empty">Connecting…</div>`;
  return html`
    <${TopBar} state=${state} connected=${connected} onPickMe=${() => setPicking(true)} route=${route} />
    <${RecordingWarning} warning=${state.recording_warning} viaApi=${state.detect !== "folder"} />
    ${(picking || !state.me) && html`
      <${ProfilePicker} state=${state} onDone=${() => setPicking(false)} closable=${!!state.me} />`}
    <div class="route"><${Router} state=${state} route=${route} /></div>
    <${Footer} />
  `;
}

function Router({ state, route }) {
  if (route === "explore") return html`<${ExplorePage} />`;
  if (route === "counter") return html`<${CounterPage} state=${state} />`;
  return html`<${ScoutPage} state=${state} />`;
}

// Per-browser UI preferences; storage can be blocked, so never let it break the page.
function loadPref(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function savePref(key, value) {
  try { localStorage.setItem(key, value); } catch {}
}

// Without recordings games show up late (found through aoe2companion) or never, so say so loudly.
function RecordingWarning({ warning, viaApi }) {
  if (!warning) return null;
  const turnOn = viaApi
    ? html`Turn on <b>Record game</b> in AoE2's game settings: Warroom still finds games through aoe2companion, but recordings show them on the loading screen instead of ~30 s into the game.`
    : html`Turn on <b>Record game</b> in AoE2's game settings, or Warroom can't see your games.`;
  const text = {
    no_folder: html`Couldn't find the AoE2 savegame folder (${String.raw`%USERPROFILE%\Games\Age of Empires 2 DE`}). Is the game installed on this PC?`,
    no_recordings: html`No recorded games found yet. ${turnOn}`,
    not_recorded: html`Your last game${warning.started
      ? ` (${new Date(warning.started).toLocaleString([], { dateStyle: "short", timeStyle: "short" })})` : ""} wasn't recorded. ${turnOn}`,
  }[warning.kind];
  return text ? html`<div class="banner" role="alert">⚠️ ${text}</div>` : null;
}

function ProfilePicker({ state, onDone, closable }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null); // null = nothing searched yet
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) { setResults(null); setError(null); return; }
    const timer = setTimeout(async () => {
      try {
        const r = await fetch(`/api/profiles/search?q=${encodeURIComponent(q)}`);
        if (!r.ok) throw new Error((await r.json()).detail || `Search failed (${r.status})`);
        setResults(await r.json());
        setError(null);
      } catch (e) {
        setError(e.message);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [query]);
  const pick = async (profileId) => {
    setSaving(true);
    await fetch("/api/me", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: profileId }),
    });
    setSaving(false);
    onDone();
  };
  return html`
    <section class="picker-panel">
      <div class="picker-head">
        <h2>${state.me ? "Change who you are" : "Who are you?"}</h2>
        ${closable && html`<button class="btn" onClick=${onDone}>Close</button>`}
      </div>
      <p class="muted">
        Warroom needs your AoE2 profile to tell your team from the enemy.
        Search your in-game name, or paste your aoe2companion profile link.
      </p>
      <input class="picker-input" type="search" placeholder="Your in-game name" autofocus
             value=${query} onInput=${(e) => setQuery(e.target.value)} disabled=${saving} />
      ${error && html`<div class="error">${error}</div>`}
      ${results && results.length === 0 && html`<div class="muted small">No players found.</div>`}
      ${results && results.length > 0 && html`
        <ul class="picker-results">
          ${results.map((r) => html`
            <li>
              <button class=${`picker-row${r.profile_id === state.me ? " current" : ""}`}
                      onClick=${() => pick(r.profile_id)} disabled=${saving}>
                ${r.avatar ? html`<img src=${r.avatar} alt="" />` : html`<span class="avatar-blank"></span>`}
                <span class="picker-who">
                  <span><b>${r.name}</b>${r.clan && html` <span class="muted">[${r.clan}]</span>`}</span>
                  <span class="muted small">
                    ${[r.country?.toUpperCase(), `${r.games.toLocaleString()} games`, r.platform, `id ${r.profile_id}`]
                      .filter(Boolean).join(" · ")}
                  </span>
                </span>
                ${r.in_recordings && html`<span class="badge">In your recordings</span>`}
                ${r.profile_id === state.me && html`<span class="badge">Current</span>`}
              </button>
            </li>`)}
        </ul>`}
      ${state.me_source === "picked" && state.detect !== "api" && html`
        <button class="link" onClick=${() => pick(null)} disabled=${saving}>
          Forget my pick and auto-detect from recordings
        </button>`}
    </section>
  `;
}

function Footer() {
  return html`
    <footer class="footer">
      Age of Empires II © Microsoft Corporation. AoE Warroom was created under Microsoft's
      "<a href="https://www.xbox.com/en-US/developers/rules" target="_blank" rel="noreferrer">Game Content Usage Rules</a>"
      using assets from Age of Empires II, and it is not endorsed by or affiliated with Microsoft.
    </footer>
  `;
}

function TopBar({ state, connected, onPickMe, route }) {
  const { match, status } = state;
  const label = { live: "Live", finished: "Last game", waiting: "Waiting for a game" }[status];
  return html`
    <header class="topbar">
      <div class="brand">AoE Warroom</div>
      <span class="status status-${status}">${label}</span>
      ${match && html`
        <span class="meta">
          <b>${match.format}</b> · ${match.map_name ?? "Unknown map"}
          ${match.started && html` · ${new Date(match.started).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`}
        </span>`}
      <span class="meta muted" title="How Warroom finds games (AOE_DETECT) and where this game came from">
        ${{ api: "API only", folder: "Recordings only", both: "Recordings + API" }[state.detect] ?? state.detect}
        ${match && ` · this game via ${match.source === "api" ? "aoe2companion" : "recording"}`}
      </span>
      <div class="spacer"></div>
      <nav class="tabs">
        <a class=${`tab${route === "/" ? " active" : ""}`} href="#/">Scout</a>
        <a class=${`tab${route === "explore" ? " active" : ""}`} href="#/explore">Explore</a>
        <a class=${`tab${route === "counter" ? " active" : ""}`} href="#/counter">Counter</a>
      </nav>
      ${!connected && html`<span class="status status-offline">Reconnecting…</span>`}
      <a class="btn" href="/overlay?preview" target="_blank" rel="noreferrer"
         title=${`OBS: add a Browser Source with URL ${location.origin}/overlay (transparent; shows the enemy team during live games)`}>
        OBS overlay
      </a>
      <button class="btn me-btn" onClick=${onPickMe}
              title=${state.me_source === "detected" ? "Guessed from your recordings. Click to change" : "Click to change"}>
        ${state.me ? html`You: <b>${state.me_name ?? `#${state.me}`}</b>` : "Set your profile"}
      </button>
      <${RecordingPicker} current=${match?.key} />
    </header>
  `;
}

// Past games to review: recordings, or your API match history in API-only mode.
function RecordingPicker({ current }) {
  const [recordings, setRecordings] = useState([]);
  const refresh = () => fetch("/api/recordings").then((r) => (r.ok ? r.json() : [])).then(setRecordings);
  const load = (key) =>
    fetch("/api/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: key || null }),
    });
  return html`
    <select class="picker" onFocus=${refresh} onChange=${(e) => load(e.target.value)}
            title="Review a past game">
      <option value="">Latest game</option>
      ${recordings.map((r) => html`
        <option value=${r.key} selected=${r.key === current}>
          ${r.started ? new Date(r.started).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : r.key}
          ${" · "}${r.map_name ?? "?"} · ${r.players}p${r.live ? " · live" : ""}
        </option>`)}
    </select>
  `;
}

function Waiting({ state }) {
  if (state.detect === "api") {
    return html`
      <div class="empty">
        <h2>Waiting for your next game</h2>
        <p>A new game shows up here 10–35 seconds into the Dark Age.</p>
      </div>
    `;
  }
  return html`
    <div class="empty">
      <h2>Waiting for your next game</h2>
      <p>As soon as a game starts, its recording appears and this page fills in.</p>
      <p class="muted">Make sure <b>Record game</b> is enabled in AoE2 settings.</p>
      <p class="muted">Watching: ${(state.watching || []).join(", ") || "no savegame folder found"}</p>
    </div>
  `;
}

// ===================== SCOUT PAGE =====================

function ScoutPage({ state }) {
  const { match, players, summary } = state;
  const [open, setOpen] = useState({});
  const [hideMine, setHideMine] = useState(() => loadPref("hideMyTeam") === "1");
  const matchKey = match?.key;
  useEffect(() => setOpen({}), [matchKey]); // new game: start collapsed
  if (!match) {
    return html`<${Waiting} state=${state} />`;
  }
  const visible = hideMine ? players.filter((p) => p.side === "enemy") : players;
  const allOpen = visible.length > 0 && visible.every((p) => open[p.number]);
  const toggleAll = () => setOpen(allOpen ? {} : Object.fromEntries(visible.map((p) => [p.number, true])));
  const toggle = (n) => setOpen((o) => ({ ...o, [n]: !o[n] }));
  const toggleMine = () => {
    savePref("hideMyTeam", hideMine ? "0" : "1");
    setHideMine(!hideMine);
  };
  return html`
    <${GamePlan} summary=${summary} players=${players} />
    <${MatchBriefing} match=${match} players=${players} />
    <div class="toolbar">
      <button class="btn" onClick=${toggleMine} aria-pressed=${hideMine}>
        ${hideMine ? "Show my team" : "Hide my team"}
      </button>
      <button class="btn" onClick=${toggleAll}>${allOpen ? "Collapse all" : "Expand all"}</button>
    </div>
    <${Teams} players=${players} match=${match} open=${open} toggle=${toggle} hideMine=${hideMine} />
  `;
}

function GamePlan({ summary, players }) {
  if (!summary) {
    const pending = players.filter((p) => p.loading).length;
    return html`<section class="plan muted">Scouting ${pending} player${pending === 1 ? "" : "s"}…</section>`;
  }
  const byNumber = Object.fromEntries(players.map((p) => [p.number, p]));
  const me = players.find((p) => p.is_me);
  const ratings = Object.entries(summary.team_ratings || {});
  return html`
    <section class="plan">
      ${summary.target && html`
        <${PlanItem} icon="🎯" title="Attack first" player=${byNumber[summary.target.number]} reasons=${summary.target.reasons} />`}
      ${summary.threat && html`
        <${PlanItem} icon="⚠️" title="Biggest threat" player=${byNumber[summary.threat.number]} reasons=${summary.threat.reasons} />`}
      ${ratings.length > 1 && html`
        <div class="plan-item ratings">
          <div class="plan-title">Average rating</div>
          ${ratings.map(([team, rating]) => html`
            <div class=${me && String(me.team) === team ? "mine" : ""}>
              ${me && String(me.team) === team ? "Your team" : `Team ${team}`}: <b>${rating}</b>
            </div>`)}
        </div>`}
    </section>
  `;
}

function PlanItem({ icon, title, player, reasons }) {
  return html`
    <div class="plan-item">
      <div class="plan-title">${icon} ${title}</div>
      <div class="plan-player">
        <span class="dot" style=${{ background: colorOf(player) }}></span>
        <b>${player.name}</b> <span class="muted">(${colorName(player)}, ${player.civ})</span>
      </div>
      <ul>${reasons.map((r) => html`<li>${r}</li>`)}</ul>
    </div>
  `;
}

function MatchBriefing({ match, players }) {
  const map = match?.map_meta;
  const [expanded, setExpanded] = useState(null);
  if (!map) return null;
  const toggle = (n) => setExpanded(expanded === n ? null : n);
  return html`
    <section class="briefing">
      <div class="briefing-map">
        <div class="briefing-head">
          <span class="chip type-${map.type}">${map.type}</span>
          <span class="briefing-title">${map.name}</span>
        </div>
        <p>${map.one_liner}</p>
        ${map.notes?.length > 0 && html`
          <ul class="briefing-notes">
            ${map.notes.map((n) => html`<li>${n}</li>`)}
          </ul>`}
      </div>
      <div class="briefing-civs">
        ${players.map((p) => html`
          <${CivBriefChip} key=${p.number} player=${p} open=${expanded === p.number} toggle=${() => toggle(p.number)} />`)}
      </div>
    </section>
  `;
}

function CivBriefChip({ player: p, open, toggle }) {
  const meta = p.civ_meta || {};
  const tags = meta.tags || [];
  return html`
    <div class=${`briefing-civ${open ? " open" : ""}`} onClick=${toggle}>
      <img class="civ-icon" src=${CIV_ICON(p.civ_slug)} alt="" onError=${(e) => (e.target.style.visibility = "hidden")} />
      <div class="briefing-civ-name">
        <b>${p.civ}</b>
        <span class="muted small">${tags.slice(0, 3).join(" · ")}</span>
      </div>
      <span class="chevron" aria-hidden="true">${open ? "▾" : "▸"}</span>
      ${open && html`
        <div class="briefing-civ-body">
          <div class="muted small">${meta.type_label}</div>
          ${meta.ideal_comp && html`<div class="row"><span class="label">Comp</span><span>${meta.ideal_comp}</span></div>`}
          ${meta.watch_out && html`<div class="row"><span class="label">Watch</span><span>${meta.watch_out}</span></div>`}
          ${meta.unique_units?.length > 0 && html`
            <div class="row"><span class="label">UU</span><span class="chips">${meta.unique_units.map((u) => html`<span class="chip">${u}</span>`)}</span></div>`}
          ${meta.unique_techs?.length > 0 && html`
            <div class="row"><span class="label">UT</span><span class="chips">${meta.unique_techs.map((t) => html`<span class="chip">${t.name} <span class="muted">(${t.age})</span></span>`)}</span></div>`}
        </div>`}
    </div>
  `;
}

function Teams({ players, match, open, toggle, hideMine }) {
  const enemies = players.filter((p) => p.side === "enemy");
  const mine = players.filter((p) => p.side !== "enemy");
  const enemyTeams = groupBy(enemies, (p) => p.team ?? "ffa");
  return html`
    <main class=${`teams${hideMine ? " hide-mine" : ""}`}>
      ${Object.entries(enemyTeams).map(([team, ps]) => html`
        <section class="team enemy">
          <h2>${team === "ffa" ? "Opponents" : match.my_team == null ? `Team ${team}` : "Enemy team"}</h2>
          ${ps.map((p) => html`<${PlayerCard} key=${p.number} player=${p} open=${!!open[p.number]} toggle=${toggle} />`)}
        </section>`)}
      ${!hideMine && html`
        <section class="team ally">
          <h2>${mine.length > 1 ? "Your team" : "You"}</h2>
          ${mine.map((p) => html`<${PlayerCard} key=${p.number} player=${p} open=${!!open[p.number]} toggle=${toggle} />`)}
        </section>`}
    </main>
  `;
}

function groupBy(items, key) {
  return items.reduce((acc, item) => ((acc[key(item)] ??= []).push(item), acc), {});
}

function PlayerCard({ player: p, open, toggle }) {
  const a = p.analysis;
  return html`
    <article class=${`card side-${p.side}${open ? " open" : ""}`} style=${{ "--player": colorOf(p) }}>
      <div class="card-head" onClick=${() => toggle(p.number)} title=${open ? "Collapse" : "Expand"}>
        <img class="civ-icon" src=${CIV_ICON(p.civ_slug)} alt="" onError=${(e) => (e.target.style.visibility = "hidden")} />
        <div class="who">
          <div class="name">
            ${p.profile_id
              ? html`<a href=${PROFILE_URL(p.profile_id)} target="_blank" rel="noreferrer" onClick=${(e) => e.stopPropagation()}>${p.name}</a>`
              : p.name}
            ${p.is_me && html`<span class="you">you</span>`}
          </div>
          <div class="sub">
            <span class="dot" style=${{ background: colorOf(p) }}></span>${colorName(p)} · ${p.civ}
            ${a?.country && html` · ${a.country.toUpperCase()}`}
          </div>
        </div>
        ${a?.rating?.rating != null && html`
          <div class="rating" title=${`Max ${a.rating.max_rating ?? "?"}`}>
            <b>${a.rating.rating}</b><span>${a.rating.leaderboard}</span>
          </div>`}
        <span class="chevron" aria-hidden="true">${open ? "▾" : "▸"}</span>
      </div>
      ${p.is_ai ? html`<div class="muted small">AI player</div>` : html`<${Summary} p=${p} />`}
      ${open && !p.is_ai && html`
        <div class="details">
          ${p.loading ? html`<div class="loading">Pulling match history…</div>`
            : a?.error ? html`<div class="error">Couldn't load history: ${a.error}</div>`
            : a && html`<${CardBody} a=${a} />`}
          ${p.playstyle && html`<${Playstyle} s=${p.playstyle} />`}
        </div>`}
    </article>
  `;
}

// At-a-glance stats, visible without expanding the card. Verdicts live in the dropdown.
function Summary({ p }) {
  const s = p.playstyle;
  const loading = !s || s.status === "loading";
  const pending = loading
    ? (s ? `Reading replays ${s.done}/${s.target}…` : "Waiting for history…")
    : "No replays available";
  const noReplays = !loading && !s.games;
  return html`
    <div class="summary">
      ${loading || noReplays
        ? ["Rush potential", "Boom or rush", "Castle Age", "Army"].map((title) => html`
          <${Tile} title=${title} label="…" advice=${pending} pending=${loading} />`)
        : html`
          <${Tile} title="Rush potential" label=${`${s.avg_feudal_army ?? "–"} units`}
                   advice="military in Feudal Age, average" />
          <${Tile} title="Boom or rush" label=${`${s.avg_tcs_by_25 ?? "–"} TCs`}
                   advice="by 25 min, average" />
          <${Tile} title="Castle Age" label=${`${s.castle_plan.avg_castles_by_25} castles`}
                   advice="by 25 min, average" />
          <${Tile} title="Army" label=${s.army.label}>
            <${GroupBar} groups=${s.army.groups} />
            <span class="tile-advice">${s.army.detail}</span>
            ${s.army.counter && html`
              <span class=${`tile-counter${p.side === "enemy" ? " build" : ""}`}>
                ${p.side === "enemy" ? "Build: " : "Weak to: "}<b>${s.army.counter}</b>
              </span>`}
          </${Tile}>`}
      <${CommsTile} comms=${p.comms} />
    </div>
    <div class="summary-tags">
      <${TagTile} p=${p} kind="strength" title=${p.side === "enemy" ? "Danger" : "Strengths"} />
      <${TagTile} p=${p} kind="weakness" title=${p.side === "enemy" ? "Exploit" : "Weaknesses"} />
    </div>
  `;
}

// The red (strength) or green (weakness) tags from history and replays, in one place.
const TAGS_SHOWN = 3;
function TagTile({ p, kind, title }) {
  const ready = p.analysis && !p.loading;
  const tags = [...(p.analysis?.insights || []), ...(p.playstyle?.insights || [])].filter((i) => i.kind === kind);
  return html`
    <div class=${`tile tag-tile tag-tile-${kind}`}>
      <span class="tile-title">${title}</span>
      ${!ready ? html`<span class="tile-advice loading">Waiting for history…</span>`
        : tags.length === 0 ? html`<span class="tile-advice muted">Nothing stands out</span>`
        : html`
          <ul>${tags.slice(0, TAGS_SHOWN).map((t) => html`<li>${t.text}</li>`)}</ul>
          ${tags.length > TAGS_SHOWN && html`<span class="tile-detail">+${tags.length - TAGS_SHOWN} more in details</span>`}`}
    </div>
  `;
}

function Tile({ title, label, level, advice, detail, pending, children }) {
  return html`
    <div class=${`tile${level ? ` level-${level}` : ""}`} title=${detail || ""}>
      <span class="tile-title">${title}</span>
      <b class="tile-label">${label}</b>
      ${children}
      ${advice && html`<span class=${`tile-advice${pending ? " loading" : ""}`}>${advice}</span>`}
      ${detail && html`<span class="tile-detail">${detail}</span>`}
    </div>
  `;
}

function CommsTile({ comms }) {
  if (!comms) return html`<${Tile} title="Comms" label="…" advice="Waiting for history…" pending=${true} />`;
  if (!comms.with.length) {
    return html`<${Tile} title="Comms" label="Solo" level="safe"
                         advice=${`No repeat teammates in their last ${comms.sample} games`} />`;
  }
  const mates = comms.with.filter((w) => w.same_team_now);
  const label = mates.length ? `Premade of ${mates.length + 1}` : "Knows lobby";
  return html`
    <div class=${`tile level-${mates.length ? "warn" : "safe"}`}>
      <span class="tile-title">Comms</span>
      <b class="tile-label">${label}</b>
      <span class="tile-advice">
        ${comms.with.map((w, i) => html`${i > 0 && ", "}${w.name} (${w.games}/${comms.sample})${!w.same_team_now && " · other team now"}`)}
      </span>
      <span class="tile-detail">Teammates in 2+ of their last ${comms.sample} games</span>
    </div>
  `;
}

function GroupBar({ groups }) {
  if (!groups?.length) return null;
  return html`
    <span class="group-bar" title=${groups.map((g) => `${g.label} ${pct(g.share)}`).join(" · ")}>
      ${groups.map((g) => html`<span style=${{ width: `${g.share * 100}%`, background: GROUP_COLORS[g.group] }}></span>`)}
    </span>
  `;
}

function ArmyByAge({ byAge }) {
  const ages = ["feudal", "castle", "imperial"].filter((age) => byAge[age]);
  if (!ages.length) return null;
  return html`
    <div class="army-ages">
      ${ages.map((age) => html`
        <div class="army-age">
          <span class="label">${age[0].toUpperCase() + age.slice(1)}</span>
          <${GroupBar} groups=${byAge[age].groups} />
          <span class="army-legend">
            ${byAge[age].groups.map((g) => html`
              <span><i style=${{ background: GROUP_COLORS[g.group] }}></i>${g.label} ${pct(g.share)}</span>`)}
            <span class="muted">· ${byAge[age].units_per_game} units/game</span>
          </span>
        </div>`)}
    </div>
  `;
}

function Playstyle({ s }) {
  if (s.status === "loading") {
    return html`
      <div class="playstyle">
        <div class="section-title">Playstyle</div>
        <div class="loading">Reading replays ${s.done}/${s.target}…</div>
      </div>`;
  }
  if (!s.games) {
    return html`
      <div class="playstyle">
        <div class="section-title">Playstyle</div>
        <div class="muted small">No recent replays available</div>
      </div>`;
  }
  const pocket = s.positions.pocket.games;
  const flank = s.positions.flank.games;
  return html`
    <div class="playstyle">
      <div class="section-title">Playstyle <span class="muted">· last ${games(s.games)} with replays</span></div>
      <div class="verdicts">
        <${Tile} title="Boom or rush" label=${s.tempo.label} level=${s.tempo.level}
                 advice=${s.tempo.advice} detail=${s.tempo.detail} />
        <${Tile} title="Castle Age" label=${s.castle_plan.label} level=${s.castle_plan.level}
                 advice=${s.castle_plan.advice} detail=${s.castle_plan.detail} />
      </div>
      ${s.insights.length > 0 && html`
        <ul class="insights">
          ${s.insights.map((i) => html`<li class=${`tag tag-${i.kind}`}>${i.text}</li>`)}
        </ul>`}
      <div class="row">
        <span class="label">Opens</span>
        <span class="chips">
          ${s.openings.map((o) => html`<span class="chip">${o.label} <b>${o.count}/${s.games}</b></span>`)}
        </span>
      </div>
      <div class="stats">
        <${Stat} label="Feudal" value=${s.feudal ? `~${s.feudal}` : "–"} title="Median time Feudal Age was reached" />
        <${Stat} label="Castle" value=${s.castle ? `~${s.castle}` : "–"} title="Median time Castle Age was reached" />
        <${Stat} label="TCs by 25 min" value=${s.avg_tcs_by_25 ?? "–"}
                 title=${`Average over ${games(s.long_games)} that lasted 25+ minutes`} />
        ${pocket + flank > 0 && html`
          <${Stat} label="Position" value=${`Pocket ${pocket} · Flank ${flank}`}
                   title=${`Pocket ${s.positions.pocket.wins}-${s.positions.pocket.decided - s.positions.pocket.wins}, `
                           + `flank ${s.positions.flank.wins}-${s.positions.flank.decided - s.positions.flank.wins}`} />`}
      </div>
      ${s.army.units?.length > 0 && html`
        <div class="row">
          <span class="label">Army</span>
          <span class="chips">
            ${s.army.units.map((u) => html`
              <span class="chip" title=${`${u.per_game} per game · countered by ${u.counters.join(", ")}`}>
                ${u.unit} <b>${pct(u.share)}</b> <span class="muted">→ ${u.counters.slice(0, 2).join(", ")}</span>
              </span>`)}
          </span>
        </div>`}
      <div class="row">
        <span class="label">Castle</span>
        <span class="chips">
          ${s.castle_plan.breakdown.map((b) => html`<span class="chip">${b.label} <b>${b.count}/${s.games}</b></span>`)}
        </span>
      </div>
      <${ArmyByAge} byAge=${s.army_by_age} />
    </div>
  `;
}

function CardBody({ a }) {
  const civ = a.current_civ;
  const map = a.current_map;
  return html`
    ${a.insights.length > 0 && html`
      <ul class="insights">
        ${a.insights.map((i) => html`<li class=${`tag tag-${i.kind}`}>${i.text}</li>`)}
      </ul>`}
    ${a.sample_size > 0 && html`<${CardStats} a=${a} civ=${civ} map=${map} />`}
  `;
}

function CardStats({ a, civ, map }) {
  return html`
    <div class="stats">
      <${Stat} label=${`Win rate (last ${a.overall.games})`} value=${pct(a.overall.win_rate)} />
      <${Stat} label="This civ" value=${civ ? (civ.played === 0 ? "First time" : `${games(civ.played)} · ${pct(civ.win_rate)}`) : "–"} />
      <${Stat} label="This map" value=${map ? (map.played === 0 ? "Never" : `${games(map.played)} · ${pct(map.win_rate)}`) : "–"} />
      <${Stat} label="Avg game" value=${a.length.avg_minutes ? `${Math.round(a.length.avg_minutes)} min` : "–"} />
      <${Stat} label="Early / late WR" value=${`${pct(a.length.short.win_rate)} / ${pct(a.length.long.win_rate)}`}
               title=${`Games under 25 min: ${a.length.short.games} · over 40 min: ${a.length.long.games}`} />
      <${Stat} label="Last 7 days" value=${games(a.games_last_week)} />
    </div>
    <div class="row">
      <span class="label">Form</span>
      <span class="form" title="Most recent on the left">
        ${a.form.map((r) => html`<span class=${`res res-${r}`}>${r}</span>`)}
      </span>
    </div>
    <div class="row">
      <span class="label">Civs</span>
      <span class="civs">
        ${a.top_civs.map((c) => html`
          <span class="civ-chip" title=${`${c.civ_name}: ${c.games} games, ${pct(c.win_rate)} win rate`}>
            <img src=${CIV_ICON(c.civ)} alt=${c.civ_name} />${c.games}
          </span>`)}
      </span>
    </div>
  `;
}

function Stat({ label, value, title }) {
  return html`<div class="stat" title=${title}><span>${label}</span><b>${value}</b></div>`;
}

// ===================== EXPLORE PAGE =====================

function ExplorePage() {
  const [options, setOptions] = useState(null);
  const [tags, setTags] = useState(new Set());
  const [focus, setFocus] = useState(new Set());
  const [units, setUnits] = useState([]);
  const [techs, setTechs] = useState([]);
  const [results, setResults] = useState([]);

  useEffect(() => {
    fetch("/api/meta/options").then((r) => r.json()).then(setOptions);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams();
    // AND semantics: each category's selected chips are joined into a single CSV;
    // the backend requires every selected tag and every selected focus to match.
    if (tags.size) params.set("tags", [...tags].join(","));
    if (focus.size) params.set("focus", [...focus].join(","));
    if (units.length) params.set("units", units.join(","));
    if (techs.length) params.set("techs", techs.join(","));
    fetch(`/api/meta/explore?${params}`)
      .then((r) => r.json())
      .then(setResults)
      .catch(() => setResults([]));
  }, [tags, focus, units, techs]);

  const toggle = (set, value) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  };

  // Strict picker: the dropdown is the source of truth. No free-text chip creation.
  const addUnit = (e) => {
    const name = e.target.value;
    if (name && !units.includes(name)) setUnits([...units, name]);
    e.target.value = "";
  };
  const addTech = (e) => {
    const name = e.target.value;
    if (name && !techs.includes(name)) setTechs([...techs, name]);
    e.target.value = "";
  };
  const removeUnit = (name) => setUnits(units.filter((u) => u !== name));
  const removeTech = (name) => setTechs(techs.filter((t) => t !== name));

  if (!options) return html`<div class="empty">Loading options…</div>`;

  return html`
    <main class="page">
      <h1 class="page-title">Explore civilizations</h1>
      <p class="muted">Pick playstyles, must-have units or technologies to find civs that fit your plan.</p>

      <section class="filter-section">
        <h2>Playstyle tags</h2>
        <div class="chip-group">
          ${options.tags.map((t) => html`
            <button class=${`chip-toggle${tags.has(t) ? " on" : ""}`}
                    onClick=${() => setTags(toggle(tags, t))}>${t}</button>`)}
        </div>
      </section>

      <section class="filter-section">
        <h2>Unit focus</h2>
        <div class="chip-group">
          ${options.unit_focus.map((f) => html`
            <button class=${`chip-toggle${focus.has(f) ? " on" : ""}`}
                    onClick=${() => setFocus(toggle(focus, f))}>${f}</button>`)}
        </div>
      </section>

      <section class="filter-section">
        <h2>Must-have units</h2>
        <select class="picker-input" onChange=${addUnit} defaultValue="">
          <option value="" disabled>Select a unit…</option>
          ${options.units.map((u) => html`<option value=${u}>${u}</option>`)}
        </select>
        <div class="chip-group">
          ${units.map((u) => html`<span class="chip" key=${u}>${u} <button onClick=${() => removeUnit(u)}>×</button></span>`)}
        </div>
      </section>

      <section class="filter-section">
        <h2>Must-have techs</h2>
        <select class="picker-input" onChange=${addTech} defaultValue="">
          <option value="" disabled>Select a tech…</option>
          ${options.techs.map((t) => html`<option value=${t}>${t}</option>`)}
        </select>
        <div class="chip-group">
          ${techs.map((t) => html`<span class="chip" key=${t}>${t} <button onClick=${() => removeTech(t)}>×</button></span>`)}
        </div>
      </section>

      <section class="results">
        <h2>${results.length} recommendation${results.length === 1 ? "" : "s"}</h2>
        <div class="result-grid">
          ${results.map((c) => html`
            <div class="result-card" key=${c.slug}>
              <div class="result-head">
                <img class="civ-icon" src=${CIV_ICON(c.slug)} alt="" />
                <div>
                  <b>${c.name}</b>
                  <span class="muted small">${c.type_label}</span>
                </div>
              </div>
              <div class="result-matched">
                ${c.matched_tags.length > 0 && html`<span class="badge">Tags: ${c.matched_tags.join(", ")}</span>`}
                ${c.matched_focus && c.matched_focus.length > 0 && html`<span class="badge">Focus: ${c.matched_focus.join(", ")}</span>`}
              </div>
              ${c.focus_gates && Object.keys(c.focus_gates).length > 0 && html`
                <div class="gate-grid" title="3 gates: bonus or UT, full upgrade chain, tier-1+2 blacksmith upgrades">
                  ${Object.entries(c.focus_gates).map(([focus, g]) => html`
                    <span class=${`gate ${g.passes ? "gate-on" : "gate-off"}`} key=${focus}>
                      <span class="gate-label">${focus}</span>
                      <span class="gate-checks">
                        <span title="Bonus / UT benefits this focus">${g.g1 ? "\u2713" : "\u2717"}</span>
                        <span title="Max unit-line tier reachable">${g.g2 ? "\u2713" : (g.g2 === null ? "-" : "\u2717")}</span>
                        <span title="Tier-1 + tier-2 blacksmith attack & armor">${g.g3 ? "\u2713" : (g.g3 === null ? "-" : "\u2717")}</span>
                      </span>
                    </span>`)}
                </div>`}
              <p class="small">${c.ideal_comp}</p>
              <div class="chips">
                ${[...(c.playstyle_tags || [])].slice(0, 5).map((t) => html`<span class="chip">${t}</span>`)}
              </div>
            </div>`)}
        </div>
      </section>
    </main>
  `;
}

// ===================== COUNTER PAGE =====================

function CounterPage({ state }) {
  const [options, setOptions] = useState(null);
  const [enemies, setEnemies] = useState([]);
  const [pendingUnit, setPendingUnit] = useState("");
  const [results, setResults] = useState(null);

  const myTeam = useMemo(() => {
    return (state?.players || [])
      .filter((p) => p.side === "me" || p.side === "ally")
      .map((p) => ({ slug: p.civ_slug, name: p.civ }));
  }, [state?.players]);

  const [selected, setSelected] = useState(() => new Set(myTeam.map((p) => p.slug)));
  useEffect(() => {
    setSelected((prev) => {
      const next = new Set(prev);
      myTeam.forEach((p) => next.add(p.slug));
      return next;
    });
  }, [myTeam]);

  useEffect(() => {
    fetch("/api/meta/options").then((r) => r.json()).then(setOptions);
  }, []);

  // Dynamic fill: trigger the counter search whenever enemies or selected civs
  // change. Skip the fetch entirely when no enemy has been picked — the
  // section just isn't rendered, which is the empty-state behavior the
  // owner asked for. Debounced 200 ms so chip-toggle flaps don't spam.
  useEffect(() => {
    if (!options) return;
    if (enemies.length === 0) { setResults(null); return; }
    const civs = [...selected].join(",");
    const url = `/api/meta/counter?units=${encodeURIComponent(enemies.join(","))}&civs=${encodeURIComponent(civs)}`;
    const handle = setTimeout(() => {
      fetch(url).then((r) => r.json()).then(setResults);
    }, 200);
    return () => clearTimeout(handle);
  }, [enemies, selected, options]);

  const addEnemy = (e) => {
    const name = e.target.value;
    if (name && !enemies.includes(name)) setEnemies([...enemies, name]);
    setPendingUnit("");
  };
  const removeEnemy = (name) => setEnemies(enemies.filter((u) => u !== name));

  const toggleCiv = (slug) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  };

  if (!options) return html`<div class="empty">Loading…</div>`;

  return html`
    <main class="page">
      <h1 class="page-title">Counter lookup</h1>
      <p class="muted">Pick the enemy units you're facing. Counters update automatically as you change the roster.</p>

      <section class="filter-section counter-search">
        <select class="picker-input" value=${pendingUnit} onChange=${addEnemy} defaultValue="">
          <option value="" disabled>Select an enemy unit…</option>
          ${options.counter_units.map((u) => html`<option value=${u}>${u}</option>`)}
        </select>
        <div class="chip-group">
          ${enemies.map((u) => html`<span class="chip" key=${u}>${u} <button onClick=${() => removeEnemy(u)}>×</button></span>`)}
        </div>
      </section>

      <section class="filter-section">
        <h2>Your team</h2>
        <div class="chip-group">
          ${(myTeam.length ? myTeam : options.civs)
            .map((c) => html`
              <button class=${`chip-toggle${selected.has(c.slug) ? " on" : ""}`}
                      onClick=${() => toggleCiv(c.slug)}>
                ${c.name}
              </button>`)}
        </div>
      </section>

      ${results && results.answers.length > 0 && html`
        <section class="results">
          ${results.answers.map((a) => html`
            <div class="counter-civ" key=${a.slug}>
              <div class="counter-civ-head">
                <img class="civ-icon" src=${CIV_ICON(a.slug)} alt="" />
                <b>${a.name}</b>
              </div>
              ${a.enemies.every((e) => e.answers.length === 0)
                ? html`<span class="muted small">No curated answer for any of these units.</span>`
                : html`
                  <div class="counter-enemies">
                    ${a.enemies.map((e, i) => e.answers.length > 0 && html`
                      <div class="counter-enemy" key=${i}>
                        <div class="counter-enemy-head">vs ${e.resolved || e.query}</div>
                        <div class="counter-answers">
                          ${e.answers.map((ans, j) => html`
                            <div class=${`counter-answer${ans.available ? "" : " unavailable"}`} key=${j}>
                              <span class="counter-answer-text">${ans.answer}</span>
                              ${ans.note && html`<span class="counter-answer-note">${ans.note}</span>`}
                              ${!ans.available && html`<span class="badge">unavailable</span>`}
                            </div>`)}
                        </div>
                      </div>`)}
                  </div>`}
            </div>`)}
        </section>`}
    </main>
  `;
}

render(html`<${App} />`, document.getElementById("app"));
