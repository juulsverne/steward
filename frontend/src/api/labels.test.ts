import { describe, expect, it } from "vitest";
import { decisionLabel, exceptionStatus, humanizeCode, invocationGloss, invocationIsTerminal, issueStatus, jobStatus, outcomeLabel, requirementLabel } from "./labels";
import type { DecisionType, IssueStatus, JobStatus } from "../types";

describe("labels", () => {
  it("maps every issue status to a label and tone", () => {
    const all: IssueStatus[] = ["CANDIDATE", "MONITORING", "ACTIONABLE", "RESOLUTION_ACTIVE", "RESOLVED", "DISPUTED", "ROUTED_EXTERNAL", "DUPLICATE", "INVALID", "ESCALATED"];
    for (const s of all) expect(issueStatus(s).label).not.toBe("");
    expect(issueStatus("RESOLVED").tone).toBe("resolved");
    expect(issueStatus("ROUTED_EXTERNAL").tone).toBe("neutral");
    expect(issueStatus("ESCALATED").tone).toBe("attention");
  });
  it("maps every job status; only VERIFIED and PAID are green", () => {
    const all: JobStatus[] = ["POSTED", "ASSIGNED", "CHECKED_IN", "PROOF_SUBMITTED", "VERIFIED", "PAID", "REWORK_REQUIRED", "REJECTED", "CANCELLED"];
    const green = all.filter((s) => jobStatus(s).tone === "resolved");
    expect(green).toEqual(["VERIFIED", "PAID"]);
    expect(jobStatus("PAID").label).toBe("Paid, simulated");
  });
  it("labels decisions and distinguishes requests from saved actions", () => {
    const all: DecisionType[] = ["MONITOR", "MARK_ACTIONABLE", "DISPUTE_OFFICIAL_STATUS", "ROUTE_EXTERNAL", "REQUEST_DISPATCH", "REQUEST_SETTLEMENT", "REQUEST_OPERATOR", "REQUEST_REWORK", "RESOLVE"];
    for (const d of all) expect(decisionLabel(d)).not.toBe("");
    expect(outcomeLabel("OK", { requested: true }).label).toBe("Requested");
    expect(outcomeLabel("OK").label).toBe("Saved");
    expect(outcomeLabel("DENIED").tone).toBe("denied");
  });
  it("keeps invocation codes verbatim and knows terminal states", () => {
    expect(invocationGloss("RUNNING").label).toBe("RUNNING");
    expect(invocationIsTerminal("WAITING")).toBe(true);
    expect(invocationIsTerminal("PENDING")).toBe(false);
    expect(exceptionStatus("PENDING").tone).toBe("attention");
  });
  it("humanizes codes and requirement keys", () => {
    expect(humanizeCode("OFFICIAL_STATUS_DISPUTED")).toBe("Official status disputed");
    expect(requirementLabel("area_clear")).toBe("Area clear");
    expect(requirementLabel("gps_within_30m")).toBe("GPS check-in within 30 m");
  });
});
