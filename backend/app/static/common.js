// Shared by the main page (app.js) and the OBS overlay (overlay.js).
import { useEffect, useState } from "./vendor/preact-htm.js";

// In-game player colors, indexed by the 0-based color id from the recording.
export const PLAYER_COLORS = ["#3d6bff", "#ff3b3b", "#2fd04a", "#ffd83a", "#2fd6d6", "#c25cff", "#a0a0a0", "#ff9a2e"];
export const COLOR_NAMES = ["Blue", "Red", "Green", "Yellow", "Cyan", "Purple", "Grey", "Orange"];
export const CIV_ICON = (slug) => `/civ-icons/${slug}.png`;

export const pct = (rate) => (rate == null ? "–" : `${Math.round(rate * 100)}%`);
export const colorOf = (p) => PLAYER_COLORS[p.color_id] ?? "#777";
export const colorName = (p) => COLOR_NAMES[p.color_id] ?? "?";
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
