import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const fixedThemeColor = /\b(?:bg|text|border|ring|divide|from|via|to|placeholder:text)-(?:white|black|gray|slate|red|rose|orange|amber|green|emerald|sky|blue|violet|purple)(?:-\d+)?(?:\/[^\s"'`}]+)?/;

test("setup settings dialogs and logs consume semantic theme colors", () => {
  const files = [
    "src/pages/SetupWizard.tsx",
    "src/components/ProviderSettingsPanel.tsx",
    "src/components/NotificationSettingsPanel.tsx",
    "src/components/AiSettingsPanel.tsx",
    "src/components/MaintenanceSettingsPanel.tsx",
    "src/components/ConfigEditor.tsx",
    "src/components/CliChecker.tsx",
    "src/components/ConnectivityTest.tsx",
    "src/components/ActionGuideDialog.tsx",
    "src/components/LogWindow.tsx",
    "src/components/ai-settings/AiScenarioEditor.tsx",
    "src/components/ai-settings/AiServiceEditor.tsx",
    "src/components/ai-settings/AiSettingsSidebar.tsx",
    "src/components/ai-settings/fields.tsx",
  ];

  for (const file of files) {
    const source = readFileSync(join(root, file), "utf8");
    assert.match(source, /var\(--ow-|ow-(?:page|modal|log|btn)/);
    assert.doesNotMatch(source, fixedThemeColor, file);
    assert.doesNotMatch(source, /transition-all|#[0-9a-f]{3,8}\b|rgba?\(/i, file);
  }
});

function readLocale(name) {
  return readFileSync(join(root, "src", "i18n", "locales", `${name}.ts`), "utf8");
}

test("advanced config tab labels stay plain and compact", () => {
  for (const locale of ["en", "zh"]) {
    const source = readLocale(locale);

    assert.match(source, /yamlTab:\s*"config\.yaml"/);
    assert.match(source, /envTab:\s*"\.env"/);
    assert.doesNotMatch(source, /yamlTab:\s*"[^"]*[📄🔐👁🔒]/u);
    assert.doesNotMatch(source, /envTab:\s*"[^"]*[📄🔐👁🔒]/u);
    assert.doesNotMatch(source, /reveal:\s*"[^"]*[📄🔐👁🔒]/u);
    assert.doesNotMatch(source, /conceal:\s*"[^"]*[📄🔐👁🔒]/u);
  }
});

test("advanced config starts from file choices instead of eager raw content", () => {
  const source = readFileSync(join(root, "src", "components", "ConfigEditor.tsx"), "utf8");

  assert.match(source, /useState<FilePanel \| null>\(null\)/);
  assert.doesNotMatch(source, /useState<ConfigSection>\("yaml"\)/);
});
