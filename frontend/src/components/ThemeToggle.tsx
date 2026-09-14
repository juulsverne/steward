import { useLayoutEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";
const KEY = "steward-theme";

// No stored choice (first visit, or storage blocked) defaults to light, matching the
// tokens in theme.css, regardless of the visitor's own OS/browser color-scheme setting.
export function readTheme(): ThemeChoice {
  try { const v = localStorage.getItem(KEY); return v === "dark" || v === "light" || v === "system" ? v : "light"; } catch { return "light"; }
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme; else root.dataset.theme = choice;
  // Store every explicit choice, "system" included, so a page refresh restores the same
  // rendering instead of silently falling back to the light default or the OS preference.
  try { localStorage.setItem(KEY, choice); } catch { /* storage blocked */ }
}

export function ThemeToggle() {
  const [choice, setChoice] = useState<ThemeChoice>(readTheme);
  // Stamp the root before the browser paints so a stored (or defaulted) choice survives
  // a refresh instead of flashing the OS color scheme until this component re-applies it.
  useLayoutEffect(() => { applyTheme(choice); }, []); // run once for the initial choice; onChange applies later ones
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
