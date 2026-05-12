import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("usage browser provides codex/claude switching and provider usage loader", () => {
  const page = readFileSync(join(root, "src", "pages", "UsageBrowser.tsx"), "utf8");
  const api = readFileSync(join(root, "src", "components", "session-browser", "api.ts"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");

  assert.match(types, /export interface ProviderUsageDay/);
  assert.match(types, /export interface ProviderUsageSummary/);
  assert.match(types, /export interface ProviderUsageQuery/);
  assert.match(types, /providerId: string;/);
  assert.match(types, /days: ProviderUsageDay\[];/);
  assert.match(types, /startDate: string;/);
  assert.match(types, /endDate: string;/);

  assert.match(api, /fetchProviderUsageSummary/);
  assert.match(api, /query: ProviderUsageQuery/);
  assert.match(api, /invoke<ProviderUsageSummary>\("get_provider_usage_summary"/);
  assert.match(api, /startDate: query\.startDate/);
  assert.match(api, /endDate: query\.endDate/);

  assert.match(page, /const PROVIDER_TABS = \["codex", "claude"\] as const;/);
  assert.match(page, /const DEFAULT_RANGE_DAYS = 7;/);
  assert.match(page, /const \[draftQuery,\s*setDraftQuery\]/);
  assert.match(page, /fetchProviderUsageSummary\(providerId,\s*query\)/);
  assert.match(page, /void loadSummary\(activeProvider,\s*query\)/);
  assert.match(page, /setQuery\(draftQuery\)/);
  assert.match(page, /type="date"/);
  assert.match(page, /t\.usage\.applyFilters/);
  assert.match(page, /t\.usage\.applying/);
  assert.match(page, /absolute inset-0 z-10 flex items-center justify-center/);
  assert.match(page, /loading \|\| refreshing/);
  assert.match(page, /t\.usage\.rangeLast7Days/);
  assert.match(page, /t\.usage\.startDate/);
  assert.match(page, /t\.usage\.endDate/);
  assert.match(page, /t\.usage\.chartTitle/);
  assert.match(page, /summary\.days\.map/);
  assert.match(page, /maxTokens/);
  assert.match(page, /height:\s*`\$\{height\}px`/);
  assert.match(page, /background:/);
  assert.match(page, /t\.usage\.title/);
  assert.match(page, /t\.usage\.providerTabs\[activeProvider\]/);
});
