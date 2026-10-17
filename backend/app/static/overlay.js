// OBS browser-source overlay: the enemy scouting report, big and readable on stream.
// Enemy info only: your own team's weaknesses on stream would help stream snipers.
//
// URL options (http://localhost:8000/overlay?...):
//   preview   also show finished games (for positioning it in OBS between games)
//   hide=90   hide this many seconds after the game started (default: stay until it ends)
//   scale=1.3 make everything bigger or smaller
import { html, render, useEffect, useState } from "./vendor/preact-htm.js";
import { CIV_ICON, GROUP_COLORS, colorName, colorOf, useLiveState } from "./common.js";

const params = new URLSearchParams(location.search);
const PREVIEW = params.has("preview");
const HIDE_AFTER = Number(params.get("hide")) || 0;
document.documentElement.style.setProperty("--scale", Number(params.get("scale")) || 1);

function useHidden(match) {
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    setHidden(false);
    if (!HIDE_AFTER || PREVIEW || !match) return;
    const elapsed = match.started ? (Date.now() - Date.parse(match.started)) / 1000 : 0;
    const timer = setTimeout(() => setHidden(true), Math.max(0, HIDE_AFTER - elapsed) * 1000);
    return () => clearTimeout(timer);
  }, [match?.key]);
  return hidden;
}

function Overlay() {
  const [state] = useLiveState();
  const match = state?.match;
  const hidden = useHidden(match);
  if (!match || hidden || (state.status !== "live" && !PREVIEW)) return null;
  const enemies = state.players.filter((p) => p.side === "enemy");
  const byNumber = Object.fromEntries(state.players.map((p) => [p.number, p]));
  const { target, threat } = state.summary || {};
  return html`
    <div class="overlay">
      <div class="head">
        <span class="brand">Warroom</span>
        <span>${match.format} · ${match.map_name ?? "Unknown map"}</span>
        ${state.status !== "live" && html`<span class="preview">preview</span>`}
      </div>
      ${(target || threat) && html`
        <div class="plan">
          ${target && html`<${PlanLine} label="Attack first" player=${byNumber[target.number]} reason=${target.reasons[0]} />`}
          ${threat && html`<${PlanLine} label="Biggest threat" player=${byNumber[threat.number]} reason=${threat.reasons[0]} />`}
        </div>`}
      ${enemies.map((p) => html`<${Enemy} key=${p.number} p=${p} />`)}
    </div>
  `;
}

function PlanLine({ label, player, reason }) {
  if (!player) return null;
  return html`
    <div class="plan-line">
      <span class="plan-label">${label}</span>
      <b style=${{ color: colorOf(player) }}>${player.name}</b>
      ${reason && html`<span class="muted"> · ${reason}</span>`}
    </div>
  `;
}

function Enemy({ p }) {
  const s = p.playstyle;
  const ready = s?.status === "done" && s.games > 0;
  const rating = p.analysis?.rating?.rating;
  const opening = ready && s.openings[0];
  const premade = p.comms?.with.filter((w) => w.same_team_now).length;
  return html`
    <div class="enemy" style=${{ "--player": colorOf(p) }}>
      <div class="enemy-head">
        <img class="civ" src=${CIV_ICON(p.civ_slug)} alt="" onError=${(e) => (e.target.style.visibility = "hidden")} />
        <span class="name">${p.name}</span>
        <span class="muted">${colorName(p)} · ${p.civ}</span>
        ${premade > 0 && html`<span class="tag warn">Premade of ${premade + 1}</span>`}
        <span class="spacer"></span>
        ${rating != null && html`<b class="rating">${rating}</b>`}
      </div>
      ${p.is_ai ? html`<div class="line muted">AI player</div>`
        : !ready ? html`<div class="line muted">${s?.status === "done" ? "No recent replays" : "Scouting…"}</div>`
        : html`
          <div class="line">
            <span class=${`tag ${s.tempo.level}`}>${s.tempo.label}</span>
            ${opening && html`<span>Opens <b>${opening.label}</b> ${opening.count}/${s.games}</span>`}
          </div>
          <div class="line numbers">
            <span><b>${s.avg_feudal_army ?? "–"}</b> Feudal units</span>
            <span><b>${s.avg_tcs_by_25 ?? "–"}</b> TCs by 25</span>
            <span><b>${s.castle_plan.avg_castles_by_25}</b> castles by 25</span>
          </div>
          <${Army} army=${s.army} />`}
    </div>
  `;
}

// Every unit they make 8%+ of (up to 5), in the age the mix comes from (usually Castle Age).
function Army({ army }) {
  if (!army.units?.length) return html`<div class="line muted">No army data yet</div>`;
  const age = army.detail.split(":")[0];
  return html`
    <div class="line army">
      <${GroupBar} groups=${army.groups} />
      <span><span class="muted">${age}:</span> ${army.units.map((u, i) => html`
        ${i > 0 && ", "}<b>${u.unit}</b> ${Math.round(u.share * 100)}%`)}</span>
    </div>
  `;
}

function GroupBar({ groups }) {
  if (!groups?.length) return null;
  return html`
    <span class="bar">
      ${groups.map((g) => html`<span style=${{ width: `${g.share * 100}%`, background: GROUP_COLORS[g.group] }}></span>`)}
    </span>
  `;
}

render(html`<${Overlay} />`, document.getElementById("overlay"));
