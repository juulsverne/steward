import { describe, expect, it } from "vitest";
import { formatTimestamp, money, plural, pointsText } from "./format";

describe("format", () => {
  it("formats cents as dollars", () => { expect(money(7200)).toBe("$72.00"); expect(money(42800)).toBe("$428.00"); expect(money(0)).toBe("$0.00"); });
  it("formats points against a threshold", () => {
    expect(pointsText(85, 70, "needed")).toBe("85 points, 70 needed");
    expect(pointsText(90, 95, "of")).toBe("90 of 95");
  });
  it("shows Unknown for a missing timestamp and a zone for a real one", () => {
    expect(formatTimestamp(null)).toBe("Unknown");
    expect(formatTimestamp("2026-09-13T00:00:00Z")).toMatch(/\d/);
  });
  it("pluralizes", () => { expect(plural(1, "source")).toBe("1 source"); expect(plural(2, "source")).toBe("2 sources"); });
});
