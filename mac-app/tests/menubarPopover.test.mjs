import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(
  join(__dirname, "..", "src", "components", "menubar-popover", "MenubarPopover.tsx"),
  "utf8",
);
const rustSource = readFileSync(
  join(__dirname, "..", "src-tauri", "src", "menubar.rs"),
  "utf8",
);

test("menubar popover keeps dynamic provider tabs and existing navigation actions", () => {
  assert.match(source, /providers\.map\(\(provider\) => \(/);
  assert.match(source, /label="总览"/);
  assert.match(source, /open_menubar_popover_session/);
  assert.match(source, /open_menubar_tab/);
  assert.match(source, /label="Tasks"/);
  assert.match(source, /label="Sessions"/);
  assert.match(source, /label="Usage"/);
});

test("menubar overview combines precision usage with provider session rails", () => {
  assert.match(source, /function OverviewRailPanel/);
  assert.match(source, /function UsageSegments/);
  assert.match(source, /style=\{\{ width: `\$\{\(\(provider\.tokensToday/);
  assert.match(source, /function SessionRailRow/);
  assert.match(source, /grid-cols-\[3px_minmax\(0,1fr\)_30px\]/);
  assert.match(source, /Latest from each provider/);
});

test("menubar provider tab uses the provider rail detail layout", () => {
  assert.match(source, /function ProviderRailPanel/);
  assert.match(source, /formatPopoverTokenCount\(provider\.tokensToday, provider\.estimated\)/);
  assert.match(source, /\{ label: "Input"/);
  assert.match(source, /\{ label: "Output"/);
  assert.match(source, /\{ label: "Cache W"/);
  assert.match(source, /\{ label: "Cache R"/);
  assert.match(source, /formatUsd\(provider\.totalCostUsd\)/);
  assert.doesNotMatch(source, /function ProviderUsageRow/);
  assert.doesNotMatch(source, /function MetricTile/);
});

test("menubar refreshes provider sessions without overlapping snapshot loads", () => {
  assert.match(
    rustSource,
    /load_provider_sessions_with_overlays\(app, &provider\.provider_id, true\)/,
  );
  assert.match(source, /const snapshotLoadInFlight = useRef\(false\)/);
  assert.match(source, /if \(snapshotLoadInFlight\.current\) \{\s*return;\s*\}/);
  assert.match(source, /snapshotLoadInFlight\.current = false/);
});
