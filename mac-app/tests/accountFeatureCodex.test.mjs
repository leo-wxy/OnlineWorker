import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const repo = new URL("../..", import.meta.url);

test("codex plugin exposes OAuth and Token import, quota refresh and explicit apply/export", async () => {
  const modal = await readFile(new URL("plugins/providers/builtin/codex/frontend/AddAccountModal.tsx", repo), "utf8");
  const overview = await readFile(new URL("plugins/providers/builtin/codex/frontend/AccountOverview.tsx", repo), "utf8");
  const backend = await readFile(new URL("plugins/providers/builtin/codex/python/account_feature.py", repo), "utf8");
  const manifest = await readFile(new URL("plugins/providers/builtin/codex/plugin.yaml", repo), "utf8");
  for (const label of ["OAuth", "Token / JSON"]) assert.match(modal, new RegExp(label.replace("/", "\\/")));
  assert.doesNotMatch(modal, /API Key|文件导入|chooseOpen|accounts\.import_(?:api_key|file)/);
  assert.doesNotMatch(backend, /accounts\.import_(?:api_key|file)/);
  for (const action of ["accounts.list", "accounts.apply", "accounts.export", "accounts.refresh"]) assert.match(overview, new RegExp(action.replace(".", "\\.")));
  assert.match(overview, /重新应用/);
  assert.match(overview, /刷新额度/);
  assert.match(overview, /remainingPercent/);
  assert.match(modal, /beginLoopback/);
  assert.match(modal, /onKeyDown/);
  for (const key of ["ArrowLeft", "ArrowRight", "Home", "End"]) assert.match(modal, new RegExp(key));
  assert.match(overview, /chooseSave/);
  assert.match(manifest, /features:\s*[\s\S]*account:\s*[\s\S]*enabled: true/);
  assert.match(manifest, /backend_entry: python\/account_feature\.py/);
});

test("account mutations keep existing rows visible during background refresh", async () => {
  const overview = await readFile(new URL("plugins/providers/builtin/codex/frontend/AccountOverview.tsx", repo), "utf8");
  const loadBody = overview.match(/const load = useCallback\(async \(\) => \{([\s\S]*?)\n  \}, \[api\]\);/)?.[1];
  assert.ok(loadBody, "account list loader should remain identifiable");
  assert.match(overview, /useState\(accounts\.length === 0\)/, "cached rows should skip the blocking loader");
  assert.match(overview, /useState<AccountSummary\[\]>\(loadAccountSummaries\)/);
  assert.match(loadBody, /parseAccountSummaries\(value\.accounts\)/);
  assert.match(loadBody, /saveAccountSummaries\(next\)/);
  assert.doesNotMatch(loadBody, /setLoading\(true\)/, "background reload must not replace existing account rows");
});

test("account summary cache is versioned and only persists display-safe fields", async () => {
  const storage = await readFile(new URL("plugins/providers/builtin/codex/frontend/accountSummaryStorage.ts", repo), "utf8");
  assert.match(storage, /onlineworker\.codex\.account-summary\.v1/);
  for (const field of ["id", "stableIdentityDisplay", "authMode", "source", "isCurrent"]) {
    assert.match(storage, new RegExp(`${field}: candidate\\.${field}`));
  }
  assert.match(storage, /quota: quotaSnapshot\(candidate\.quota\)/);
  assert.doesNotMatch(storage, /\.\.\.candidate/);
  assert.doesNotMatch(storage, /credentials|access_token|refresh_token|OPENAI_API_KEY/);
});

test("account export opens the native save flow without reloading the account list", async () => {
  const overview = await readFile(new URL("plugins/providers/builtin/codex/frontend/AccountOverview.tsx", repo), "utf8");
  const exportBody = overview.match(/const exportIds = async \(ids: string\[\]\) => \{([\s\S]*?)\n  \};/)?.[1];
  assert.ok(exportBody, "account export flow should remain identifiable");
  assert.match(exportBody, /api\.chooseSave\("codex-accounts\.json"\)/);
  assert.doesNotMatch(exportBody, /window\.confirm/);
  assert.match(overview, /run\("export", \(\) => exportIds\(selectedIds\), false\)/);
  assert.match(overview, /run\("export", \(\) => exportIds\(\[account\.id\]\), false\)/);
});

test("account overview uses the compact selectable account-list contract", async () => {
  const overview = await readFile(new URL("plugins/providers/builtin/codex/frontend/AccountOverview.tsx", repo), "utf8");
  const styles = await readFile(new URL("plugins/providers/builtin/codex/frontend/account.css", repo), "utf8");
  for (const label of ["账号库", "全选当前结果", "清除选择", "导出选中", "暂无账号", "当前账号", "未应用"]) assert.match(overview, new RegExp(label));
  assert.match(overview, /codex-account-row-current/);
  assert.match(styles, /codex-account-list-toolbar/);
  assert.match(styles, /codex-account-row[\s\S]*grid-template-columns/);
  assert.match(styles, /grid-template-columns:\s*minmax\(15rem, 1\.05fr\) minmax\(17rem, 0\.95fr\) 11\.75rem/);
  assert.match(styles, /codex-account-row-actions[\s\S]*grid-template-columns:\s*5\.5rem 2\.75rem 2\.75rem/);
  assert.match(overview, /codex-account-primary-action/);
  assert.doesNotMatch(styles, /codex-account-grid/);
});

test("codex session assets are grouped, deferred and reversible", async () => {
  const page = await readFile(new URL("plugins/providers/builtin/codex/frontend/SessionAssetsPage.tsx", repo), "utf8");
  for (const action of ["sessions.list", "sessions.usage", "sessions.import", "sessions.export", "sessions.trash", "sessions.restore", "sessions.repair"]) {
    assert.match(page, new RegExp(action.replace(".", "\\.")));
  }
  assert.match(page, /chooseOpen/);
  assert.match(page, /chooseSave/);
  assert.match(page, /function grouped/);
  assert.match(page, /<details/);
  assert.match(page, /工作目录/);
  assert.match(page, /usageLoading/);
  const loadBody = page.match(/const load = useCallback\(async \(\) => \{([\s\S]*?)\n  \}, \[api, kind, search, trash\]\);/)?.[1];
  const summary = page.match(/<summary[\s\S]*?<\/summary>/)?.[0];
  assert.ok(loadBody, "session loader should remain identifiable");
  assert.ok(summary, "session group summary should remain identifiable");
  assert.doesNotMatch(loadBody, /setLoading\(true\)/, "background refresh must keep existing groups visible");
  assert.doesNotMatch(summary, /<input/, "group selection must be a sibling of the disclosure control");
  assert.doesNotMatch(page, /text-white/);
  assert.doesNotMatch(page, /permanent|delete_provider_session|list_provider_sessions|get_usage_source_summary/);
});

test("destructive and credential mutations use the plugin confirmation dialog", async () => {
  const overview = await readFile(new URL("plugins/providers/builtin/codex/frontend/AccountOverview.tsx", repo), "utf8");
  const sessions = await readFile(new URL("plugins/providers/builtin/codex/frontend/SessionAssetsPage.tsx", repo), "utf8");
  const dialog = await readFile(new URL("plugins/providers/builtin/codex/frontend/ConfirmActionDialog.tsx", repo), "utf8");
  assert.doesNotMatch(`${overview}${sessions}`, /window\.confirm/);
  assert.match(overview, /setPendingApply\(account\)/);
  assert.match(sessions, /setPendingAction\("repair"\)/);
  assert.match(sessions, /setPendingAction\("trash"\)/);
  assert.match(dialog, /<dialog/);
  assert.match(dialog, /showModal\(\)/);
  assert.match(dialog, /onCancel/);
  assert.doesNotMatch(dialog, /createPortal|addEventListener/);
});
