import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Tabs } from "./Tabs";

const TABS = [
  { id: "patients", label: "Patients" },
  { id: "calls", label: "Calls" },
] as const;

describe("Tabs", () => {
  it("selects one tab and keeps only it in the tab order", () => {
    const html = renderToStaticMarkup(
      <Tabs label="Dashboard" tabs={TABS} selected="calls" onSelect={() => {}} />,
    );

    expect(html).toContain('role="tablist"');
    expect(html).toContain('aria-label="Dashboard"');
    expect(html).toMatch(/id="tab-patients"[^>]*aria-selected="false"[^>]*tabindex="-1"/);
    expect(html).toMatch(/id="tab-calls"[^>]*aria-selected="true"[^>]*tabindex="0"/);
    expect(html).toContain('aria-controls="panel-calls"');
  });
});
