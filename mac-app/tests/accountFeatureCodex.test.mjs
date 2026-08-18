import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const repo = new URL("../..", import.meta.url);

test("codex plugin exposes four import paths, quota refresh and explicit apply/export", async () => {
  const modal = await readFile(new URL("plugins/providers/builtin/codex/frontend/AddAccountModal.tsx", repo), "utf8");
  const overview = await readFile(new URL("plugins/providers/builtin/codex/frontend/AccountOverview.tsx", repo), "utf8");
  const manifest = await readFile(new URL("plugins/providers/builtin/codex/plugin.yaml", repo), "utf8");
  for (const label of ["OAuth 授权", "Token / JSON", "API Key", "导入"]) assert.match(modal, new RegExp(label.replace("/", "\\/")));
  for (const action of ["accounts.list", "accounts.apply", "accounts.export", "accounts.refresh"]) assert.match(overview, new RegExp(action.replace(".", "\\.")));
  assert.match(overview, /重新应用/);
  assert.match(overview, /刷新额度/);
  assert.match(overview, /remainingPercent/);
  assert.match(modal, /beginLoopback/);
  assert.match(modal, /chooseOpen/);
  assert.match(overview, /chooseSave/);
  assert.match(manifest, /features:\s*[\s\S]*account:\s*[\s\S]*enabled: true/);
  assert.match(manifest, /backend_entry: python\/account_feature\.py/);
});

test("account mutations keep existing rows visible during background refresh", async () => {
  const overview = await readFile(new URL("plugins/providers/builtin/codex/frontend/AccountOverview.tsx", repo), "utf8");
  const loadBody = overview.match(/const load = useCallback\(async \(\) => \{([\s\S]*?)\n  \}, \[api\]\);/)?.[1];
  assert.ok(loadBody, "account list loader should remain identifiable");
  assert.match(overview, /useState\(true\)/, "initial account load still needs a loading state");
  assert.doesNotMatch(loadBody, /setLoading\(true\)/, "background reload must not replace existing account rows");
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
  for (const label of ["全选当前结果", "清除选择", "导出选中", "暂无账号", "当前账号", "当前未使用"]) assert.match(overview, new RegExp(label));
  assert.match(overview, /codex-account-card-current/);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*grid-template-columns:[\s\S]*grid-column: 1 \/ -1/);
  assert.match(styles, /@media \(min-width: 1280px\)[\s\S]*grid-template-columns:/);
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
