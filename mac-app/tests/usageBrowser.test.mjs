import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { buildDefaultUsageQuery } from "../src/utils/usageDateRange.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const fixedThemeColor = /\b(?:bg|text|border|ring|divide|from|via|to|decoration|marker)-(?:white|black|gray|slate|red|rose|orange|amber|green|emerald|sky|blue|violet|purple)(?:-\d+)?(?:\/[^\s"'`}]+)?/;

test("sessions usage and commands consume semantic theme colors", () => {
  const files = [
    "src/pages/UsageBrowser.tsx",
    "src/pages/CommandRegistry.tsx",
    "src/components/session-browser/GenericProviderChat.tsx",
    "src/components/session-browser/SessionMarkdown.tsx",
    "src/components/session-browser/archive.tsx",
    "src/components/session-browser/badges.tsx",
    "src/components/session-browser/navigation.tsx",
    "src/components/session-browser/presentation.tsx",
    "src/components/session-browser/shared.tsx",
    "src/components/session-browser/workspaceActions.tsx",
    "src/utils/sessionMarkdown.js",
  ];

  for (const file of files) {
    const source = readFileSync(join(root, file), "utf8");
    assert.match(source, /var\(--ow-/);
    assert.doesNotMatch(source, fixedThemeColor, file);
    assert.doesNotMatch(source, /transition-all|transition:\s*all|#[0-9a-f]{3,8}\b|rgba?\(/i, file);
  }

  const shared = readFileSync(join(root, "src", "components", "session-browser", "shared.tsx"), "utf8");
  assert.match(shared, /\[background:var\(--ow-primary-surface\)\]/);
  assert.match(shared, /\[box-shadow:var\(--ow-shadow-md\)\]/);
});

test("usage browser discovers all usage sources from the usage catalog", () => {
  const page = readFileSync(join(root, "src", "pages", "UsageBrowser.tsx"), "utf8");
  const api = readFileSync(join(root, "src", "components", "session-browser", "api.ts"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");
  const dateRange = readFileSync(join(root, "src", "utils", "usageDateRange.js"), "utf8");

  assert.match(types, /export interface UsageSourceDay/);
  assert.match(types, /export interface UsageSourceSummary/);
  assert.match(types, /export interface UsageQuery/);
  assert.match(types, /sourceId: string;/);
  assert.match(types, /days: UsageSourceDay\[];/);
  assert.match(types, /startDate: string;/);
  assert.match(types, /endDate: string;/);
  assert.match(types, /usage: boolean;/);

  assert.match(api, /fetchUsageSourceSummary/);
  assert.match(api, /fetchUsageSourceCatalog/);
  assert.match(api, /query: UsageQuery/);
  assert.match(api, /invoke<UsageSourceSummary>\("get_usage_source_summary"/);
  assert.match(api, /startDate: query\.startDate/);
  assert.match(api, /endDate: query\.endDate/);

  assert.doesNotMatch(page, /const PROVIDER_TABS = \["codex", "claude"\] as const;/);
  assert.match(page, /fetchUsageSourceCatalog/);
  assert.match(page, /metadata\.filter\(\(source\) => Boolean\(source\.providerId\)\)/);
  assert.doesNotMatch(page, /visibleUsageProviders/);
  assert.match(dateRange, /const DEFAULT_RANGE_DAYS = 7;/);
  assert.match(dateRange, /function localIsoDate\(date\)/);
  assert.match(dateRange, /export function buildDefaultUsageQuery/);
  assert.match(page, /import \{ buildDefaultUsageQuery \} from "\.\.\/utils\/usageDateRange"/);
  assert.match(page, /const autoRangeRef = useRef\(true\)/);
  assert.match(page, /const refreshUsage = useCallback/);
  assert.match(page, /const summaryRequestIdRef = useRef\(0\)/);
  assert.match(page, /const usageSummaryCache = new Map<string, UsageSourceSummary>\(\)/);
  assert.match(page, /usageSummaryCache\.get\(cacheKey\)/);
  assert.match(page, /usageSummaryCache\.set\(cacheKey, next\)/);
  assert.match(page, /usageSummaryCache\.size > 24/);
  assert.match(page, /const forceNextLoadRef = useRef\(false\)/);
  assert.match(page, /requestId !== summaryRequestIdRef\.current/);
  assert.doesNotMatch(page, /if \(next\.startDate === query\.startDate/);
  assert.match(page, /autoRangeRef\.current = false/);
  assert.match(page, /const \[draftQuery,\s*setDraftQuery\]/);
  assert.match(page, /fetchUsageSourceSummary\(source\.pluginId, source\.sourceId, query, forceRefresh\)/);
  assert.match(page, /activeProvider\?\.sourceId/);
  assert.match(page, /setQuery\(draftQuery\)/);
  assert.match(page, /type="date"/);
  assert.match(page, /t\.usage\.applyFilters/);
  assert.match(page, /t\.usage\.applying/);
  assert.match(page, /absolute inset-0 z-10 flex items-center justify-center/);
  assert.match(page, /loading \|\| refreshing/);
  assert.match(page, /\{loading && \(/);
  assert.doesNotMatch(page, /\{\(loading \|\| refreshing\) && \(/);
  assert.match(page, /t\.usage\.rangeLast7Days/);
  assert.match(page, /t\.usage\.startDate/);
  assert.match(page, /t\.usage\.endDate/);
  assert.match(page, /t\.usage\.chartTitle/);
  assert.match(page, /summary\.days\.map/);
  assert.match(page, /maxTokens/);
  assert.match(page, /height:\s*`\$\{height\}px`/);
  assert.match(page, /background:/);
  assert.match(page, /t\.usage\.title/);
  assert.match(page, /function describeUnknownError\(error: unknown, fallback: string\)/);
  assert.match(page, /if \(!next \|\| typeof next !== "object"\) \{/);
  assert.match(page, /setError\(describeUnknownError\(loadError, t\.usage\.unavailable\)\);/);
  assert.doesNotMatch(page, /t\.usage\.providerTabs\[activeProvider\]/);
});

test("usage browser default range rolls forward on local date", () => {
  assert.deepEqual(
    buildDefaultUsageQuery(new Date(2026, 5, 5, 0, 5, 0)),
    {
      startDate: "2026-05-30",
      endDate: "2026-06-05",
    },
  );
});

test("usage token detail table keeps its own bounded scroll area", () => {
  const page = readFileSync(join(root, "src", "pages", "UsageBrowser.tsx"), "utf8");

  assert.match(page, /<div className="flex min-h-0 flex-1 flex-col">/);
  assert.match(page, /<div className="min-h-0 flex-1 overflow-auto rounded-2xl border border-\[var\(--ow-line-soft\)\] bg-\[var\(--ow-panel\)\]">/);
  assert.match(page, /<thead className="sticky top-0 z-\[1\] bg-\[var\(--ow-toolbar\)\]">/);
});
