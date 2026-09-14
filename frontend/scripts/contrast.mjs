// Reads src/theme.css, computes WCAG contrast for the pairs the interface relies on, exits 1 below 4.5.
import { readFileSync } from "node:fs";
const css = readFileSync(new URL("../src/theme.css", import.meta.url), "utf8");
const block = (selector) => {
  const start = css.indexOf(selector); const open = css.indexOf("{", start); let depth = 0; let i = open;
  for (; i < css.length; i++) { if (css[i] === "{") depth++; if (css[i] === "}") { depth--; if (depth === 0) break; } }
  return css.slice(open, i);
};
const tokens = (text) => Object.fromEntries([...text.matchAll(/(--[a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})/g)].map((m) => [m[1], m[2]]));
const lum = (hex) => { const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const pairs = [["--ink", "--canvas"], ["--ink", "--surface"], ["--ink-2", "--canvas"], ["--ink-2", "--surface"],
  ["--ink-3", "--canvas"], ["--ink-3", "--surface"], ["--action", "--canvas"], ["--action", "--surface"],
  ["--on-action", "--action"], ["--focus", "--canvas"], ["--focus", "--surface"], ["--action", "--action-soft"]];
for (const s of ["watching", "active", "attention", "resolved", "denied", "neutral"]) pairs.push([`--status-${s}-fg`, `--status-${s}-bg`]);
let failed = false;
for (const [name, text] of [["light", block(":root")], ["dark", block('[data-theme="dark"]')]]) {
  const t = tokens(text);
  for (const [fg, bg] of pairs) { const r = ratio(t[fg], t[bg]);
    const ok = r >= 4.5; if (!ok) failed = true;
    console.log(`${ok ? "ok  " : "FAIL"} ${name.padEnd(5)} ${fg.padEnd(24)} on ${bg.padEnd(22)} ${r.toFixed(2)}`); }
}
process.exit(failed ? 1 : 0);
