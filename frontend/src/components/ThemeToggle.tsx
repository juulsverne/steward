import { useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";
const KEY = "steward-theme";

export function readTheme(): ThemeChoice {
  try { const v = localStorage.getItem(KEY); return v === "dark" || v === "light" ? v : "system"; } catch { return "system"; }
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") { delete root.dataset.theme; try { localStorage.removeItem(KEY); } catch { /* storage blocked */ } }
  else { root.dataset.theme = choice; try { localStorage.setItem(KEY, choice); } catch { /* storage blocked */ } }
}

export function ThemeToggle() {
  const [choice, setChoice] = useState<ThemeChoice>(readTheme);
  return (
    <label className="theme-toggle small">
      <span>Theme</span>
      <select value={choice} onChange={(e) => { const next = e.target.value as ThemeChoice; setChoice(next); applyTheme(next); }}>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
        <option value="system">System</option>
      </select>
    </label>
  );
}
