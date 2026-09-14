import { switchPersona, useSession } from "../api/session";
import type { PersonaChoice } from "../types";

const GROUPS: Array<[string, string]> = [["operator", "Operator"], ["crew", "Crew"], ["resident", "Resident"]];

export function PersonaSwitcher() {
  const s = useSession();
  const personas = (s.session?.personas ?? []) as PersonaChoice[];
  const current = personas.find((p) => p.label === s.session?.actor?.label)?.persona_id ?? "";
  return (
    <div className="persona-switcher">
      <label className="small">
        <span>Persona</span>
        <select value={current} disabled={s.switching || s.status !== "ready"} onChange={(e) => { void switchPersona(e.target.value); }}>
          <option value="" disabled>Select a persona</option>
          {GROUPS.map(([type, title]) => (
            <optgroup key={type} label={title}>
              {personas.filter((p) => p.actor_type === type).map((p) => <option key={p.persona_id} value={p.persona_id}>{p.label}</option>)}
            </optgroup>
          ))}
        </select>
      </label>
      {s.switchError && <p role="alert" className="small persona-switcher__error">{s.switchError}. Previous persona kept.</p>}
    </div>
  );
}
