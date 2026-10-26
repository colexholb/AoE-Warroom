// Shared by the main page (app.js) and the OBS overlay (overlay.js).
import { useEffect, useState } from "./vendor/preact-htm.js";

// In-game player colors, indexed by the 0-based color id from the recording.
export const PLAYER_COLORS = ["#3d6bff", "#ff3b3b", "#2fd04a", "#ffd83a", "#2fd6d6", "#c25cff", "#a0a0a0", "#ff9a2e"];
export const COLOR_NAMES = ["Blue", "Red", "Green", "Yellow", "Cyan", "Purple", "Grey", "Orange"];
export const CIV_ICON = (slug) => `/civ-icons/${slug}.png`;

// Lighter variants of the same hues, for when a color is used as *text* (the SSD tab
// colors player names). PLAYER_COLORS were picked to fill a dot; as text on the dark
// panel, blue and red fall under 4.5:1. Every variant here clears 4.5:1 on --panel-2
// (the lightest background a colored name can sit on); the worst is 6.38:1.
export const PLAYER_COLORS_TEXT = ["#7ba1ff", "#ff7b7b", "#5fe08a", "#ffd83a", "#5fe4e4", "#d38bff", "#c0c0c0", "#ffb066"];

export const pct = (rate) => (rate == null ? "–" : `${Math.round(rate * 100)}%`);
export const colorOf = (p) => PLAYER_COLORS[p.color_id] ?? "#777";
export const colorName = (p) => COLOR_NAMES[p.color_id] ?? "?";
// Same color as `colorOf`, but legible as text on the dark background.
export const colorOfText = (p) => PLAYER_COLORS_TEXT[p.color_id] ?? "#ccc";
export const GROUP_COLORS = {
  ranged: "#5fa8ff", cavalry: "#e0a34a", infantry: "#e07070", siege: "#a08cff",
  monk: "#e6d36b", navy: "#4ec9c0", other: "#8a8a8a",
};

export function useLiveState() {
  const [state, setState] = useState(null);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    const source = new EventSource("/api/events");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false); // EventSource reconnects on its own
    source.onmessage = (e) => setState(JSON.parse(e.data));
    return () => source.close();
  }, []);
  return [state, connected];
}
