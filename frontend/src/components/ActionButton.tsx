import type { ButtonHTMLAttributes } from "react";
type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "quiet"; pending?: boolean; pendingLabel?: string };
export function ActionButton({ variant = "primary", pending = false, pendingLabel = "Working", children, disabled, className = "", ...rest }: Props) {
  return (
    <button type="button" {...rest} className={`btn btn--${variant} ${className}`} disabled={disabled || pending} aria-busy={pending || undefined}>
      {pending ? pendingLabel : children}
    </button>
  );
}
