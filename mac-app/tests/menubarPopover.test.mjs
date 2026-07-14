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
  assert.match(source, />Sessions<\/h3>/);
  assert.match(source, /Latest from each provider/);
  assert.match(source, /const status = lane\?\.status \|\| "Idle"/);
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
    /load_provider_sessions_with_overlays\(&app, &provider_id, force_refresh\)/,
  );
  assert.match(rustSource, /tokio::join!\(/);
  assert.match(rustSource, /let mut tasks = JoinSet::new\(\)/);
  assert.match(rustSource, /get_usage_source_catalog\(app\.clone\(\)\)/);
  assert.match(rustSource, /source\.provider_id\.as_deref\(\) == Some\(provider_id\)/);
  assert.match(source, /forceRefresh = false/);
  assert.match(source, /forceRefresh,\s*\}\);/);
  assert.match(source, /loadSnapshot\(false\)/);
  assert.match(source, /loadSnapshot\(true\)/);
  assert.match(source, /listen<MenubarPopoverSnapshot>\(SNAPSHOT_UPDATED_EVENT/);
  assert.doesNotMatch(
    source,
    /onFocusChanged[\s\S]*if \(!focused\)[\s\S]*loadSnapshot\(false\)/,
  );
  assert.match(source, /const snapshotLoadInFlight = useRef\(false\)/);
  assert.match(source, /if \(snapshotLoadInFlight\.current\) \{\s*return;\s*\}/);
  assert.match(source, /snapshotLoadInFlight\.current = false/);
  assert.match(rustSource, /MENUBAR_PROVIDER_LOAD_TIMEOUT: Duration = Duration::from_secs\(3\)/);
  assert.match(rustSource, /tokio::time::timeout\(/);
  assert.match(rustSource, /MenubarPopoverSnapshotStore/);
  assert.match(
    rustSource,
    /if !force_refresh\.unwrap_or\(false\)[\s\S]*state::<MenubarPopoverSnapshotStore>\(\)[\s\S]*\.read\(\)/,
  );
  assert.match(
    rustSource,
    /start_menubar_snapshot_refresh_loop\(app\.clone\(\)\)/,
  );
  assert.match(rustSource, /SNAPSHOT_REFRESH_INTERVAL_SECONDS: u64 = 10/);
  assert.match(rustSource, /ticker\.set_missed_tick_behavior\(MissedTickBehavior::Skip\)/);
  assert.match(rustSource, /refresh_menubar_popover_snapshot\(&app, false\)\.await/);
  assert.match(rustSource, /MENUBAR_POPOVER_SNAPSHOT_EVENT/);
});

test("menubar preloads the popover offscreen before the first tray click", () => {
  assert.match(
    rustSource,
    /pub\(crate\) fn setup_menubar[\s\S]*ensure_popover_window\(app\)[\s\S]*let tray = build_tray\(app\)/,
  );
  assert.match(rustSource, /MENUBAR_POPOVER_WARMUP_POSITION/);
  assert.match(rustSource, /\.visible\(true\)/);
  assert.match(rustSource, /\.focused\(false\)/);
  assert.match(rustSource, /\.on_page_load\(/);
  assert.match(rustSource, /PageLoadEvent::Finished/);
  assert.match(rustSource, /refresh_menubar_popover_snapshot\(&app, false\)\.await/);
  assert.match(rustSource, /popover_window_is_warming\(&window\)/);
  assert.match(rustSource, /window\.hide\(\)/);
});
