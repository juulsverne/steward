import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { ThemeToggle, applyTheme } from "./ThemeToggle";

describe("ThemeToggle", () => {
  beforeEach(() => { localStorage.clear(); delete document.documentElement.dataset.theme; });

  it("stores only the theme and stamps the root element", async () => {
    render(<ThemeToggle />);
    await userEvent.selectOptions(screen.getByLabelText("Theme"), "dark");
    expect(localStorage.getItem("steward-theme")).toBe("dark");
    expect(localStorage.length).toBe(1);
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("system choice removes the stamp and the stored value", () => {
    applyTheme("dark");
    applyTheme("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(localStorage.getItem("steward-theme")).toBeNull();
  });
});
