import type { ReactNode } from "react";
export function Notice({ tone, title, children, role }: { tone: "info" | "warning" | "error" | "success"; title?: ReactNode; children?: ReactNode; role?: "alert" | "status" }) {
  return (
    <div className={`notice notice--${tone}`} role={role ?? (tone === "error" ? "alert" : undefined)}>
      {title && <p className="notice__title">{title}</p>}
      {children && <div className="notice__body">{children}</div>}
    </div>
  );
}
