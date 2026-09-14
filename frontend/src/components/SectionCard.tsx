import type { ReactNode } from "react";
export function SectionCard({ title, id, action, children }: { title: ReactNode; id?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="card" id={id} aria-labelledby={id ? `${id}-title` : undefined}>
      <header className="card__header"><h2 id={id ? `${id}-title` : undefined}>{title}</h2>{action && <div className="card__action">{action}</div>}</header>
      <div className="card__body">{children}</div>
    </section>
  );
}
