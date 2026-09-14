import type { ReactNode } from "react";
export function PageHeader({ eyebrow, title, meta, actions }: { eyebrow?: ReactNode; title: ReactNode; meta?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div className="page-header__text">
        {eyebrow && <p className="page-header__eyebrow small">{eyebrow}</p>}
        <h1>{title}</h1>
        {meta && <div className="page-header__meta row small">{meta}</div>}
      </div>
      {actions && <div className="page-header__actions row">{actions}</div>}
    </header>
  );
}
