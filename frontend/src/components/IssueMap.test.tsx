import { describe, expect, it } from "vitest";
import type { BoardMarker } from "../types";
import { markerPopup } from "./IssueMap";

describe("markerPopup", () => {
  it("builds the popup with DOM APIs only, so a resident-supplied label cannot inject markup", () => {
    const label = '<img src=x onerror="window.__x=1">';
    const marker: BoardMarker = { issue_id: "demo/couch 1", label, marker_state: "watching", status: "CANDIDATE", simulated: true };
    const popup = markerPopup(marker);
    expect(popup.querySelector("img")).toBeNull();
    expect(popup.textContent).toContain(label);
    const anchor = popup.querySelector("a");
    expect(anchor).not.toBeNull();
    expect(anchor!.getAttribute("href")).toEqual(expect.stringMatching(new RegExp(`${encodeURIComponent(marker.issue_id)}$`)));
  });
});
