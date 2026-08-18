import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const repo = new URL("../..", import.meta.url);

test("shared account host stays provider neutral", async () => {
  const host = await readFile(new URL("mac-app/src/components/AccountFeatureHost.tsx", repo), "utf8");
  assert.doesNotMatch(host, /Codex|accounts\.apply|sessions\.list|OPENAI_API_KEY|refresh_token/);
  assert.match(host, /invoke_account_feature/);
  assert.match(host, /choose_account_feature_file/);
  assert.match(host, /begin_account_feature_loopback/);
});

test("plugin frontend keeps secrets and live surfaces out of persistence", async () => {
  const files = ["AccountOverview.tsx", "AddAccountModal.tsx", "SessionAssetsPage.tsx"];
  const source = (await Promise.all(files.map((name) => readFile(new URL(`plugins/providers/builtin/codex/frontend/${name}`, repo), "utf8")))).join("\n");
  assert.doesNotMatch(source, /localStorage|sessionStorage|provider_owner_bridge|list_provider_sessions|get_usage_source_summary/);
  assert.doesNotMatch(source, /native_paths|data_root|CODEX_HOME/);
  assert.match(source, /type="password"/);
});
