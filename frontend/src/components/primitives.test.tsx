import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { ActionButton } from "./ActionButton";
import { EvidenceImage } from "./EvidenceImage";
import { Money } from "./Money";
import { Points } from "./Points";
import { ErrorNotice, SavedState } from "./States";
import { StatusBadge } from "./StatusBadge";

describe("primitives", () => {
  it("StatusBadge always renders the word", () => {
    render(<StatusBadge label="Resolved" tone="resolved" />);
    expect(screen.getByText("Resolved")).toHaveClass("badge--resolved");
  });
  it("Points reads as points against a threshold, never a percentage", () => {
    render(<><Points value={85} threshold={70} /><Points value={90} threshold={95} style="of" suffix="for payment" /></>);
    expect(screen.getByText("85 points, 70 needed")).toBeInTheDocument();
    expect(screen.getByText("90 of 95 for payment")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("%");
  });
  it("Money adds simulated when asked", () => {
    render(<Money cents={7200} simulated />);
    expect(screen.getByText(/\$72\.00/)).toHaveTextContent("simulated");
  });
  it("EvidenceImage uses the safe content URL, scoped job id and alt text, and falls back on error", () => {
    render(<EvidenceImage evidenceId="ev-1" role="After" observedAt="2026-09-13T00:00:00Z" jobId="job-1" />);
    const img = screen.getByRole("img") as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("/api/evidence/ev-1/content?job_id=job-1");
    expect(img.alt).toMatch(/^After photo, observed /);
    fireEvent.error(img);
    expect(screen.getByText(/Image unavailable/)).toHaveTextContent("ev-1");
  });
  it("ActionButton disables while pending and keeps an accessible name", () => {
    render(<ActionButton pending pendingLabel="Working">Request completion</ActionButton>);
    const button = screen.getByRole("button");
    expect(button).toBeDisabled(); expect(button).toHaveTextContent("Working");
  });
  it("ErrorNotice shows the reason text and a retry action", () => {
    const retry = vi.fn();
    render(<ErrorNotice error={new ApiError(503, { outcome: "ERROR", reason_code: "STORAGE_UNAVAILABLE" })} onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Storage unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Retry" })); expect(retry).toHaveBeenCalled();
  });
  it("SavedState shows the verbatim invocation status", () => {
    render(<SavedState phase="processing" status="RUNNING" />);
    expect(screen.getByText("RUNNING")).toBeInTheDocument();
    expect(screen.getByText(/Steward is processing/)).toBeInTheDocument();
  });
});
