import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

test("maintenance exposes bounded diagnostics and local support bundle actions", () => {
  const source = read("src/components/MaintenanceSettingsPanel.tsx");

  assert.match(source, /invoke<DiagnosticReport>\("run_support_diagnostics"\)/);
  assert.match(source, /invoke<SupportBundleExportResult \| null>\("export_support_bundle"\)/);
  assert.match(source, /invoke\("reveal_support_bundle", \{ path: supportBundle\.path \}\)/);
  assert.match(source, /diagnosticsBusy \|\| exportBusy/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /aria-expanded=/);

  const backend = read("src-tauri/src/commands/support_bundle.rs");
  assert.match(backend, /get_provider_plugin_load_failures/);
  assert.match(backend, /get_usage_source_catalog/);
  assert.match(backend, /get_usage_source_summary/);
});

test("support bundle copy exists in both locales and states privacy boundaries", () => {
  const zh = read("src/i18n/locales/zh.ts");
  const en = read("src/i18n/locales/en.ts");

  for (const source of [zh, en]) {
    assert.match(source, /runDiagnostics:/);
    assert.match(source, /exportSupportBundle:/);
    assert.match(source, /revealSupportBundle:/);
    assert.match(source, /supportBundlePrivacy:/);
  }
  assert.match(zh, /不会读取 Session 数据库或完整会话记录/);
  assert.match(zh, /最近运行日志可能包含/);
  assert.match(en, /does not read the Session database or full conversations/i);
  assert.match(en, /recent logs may contain/i);
});
