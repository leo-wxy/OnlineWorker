import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("app shell wires a collapsible narrow sidebar state", () => {
  const app = readFileSync(join(root, "src", "App.tsx"), "utf8");

  assert.match(app, /const \[sidebarCollapsed,\s*setSidebarCollapsed\] = useState\(false\);/);
  assert.match(app, /sidebarCollapsed \? "w-\[84px\]" : "w-\[248px\]"/);
  assert.match(app, /setSidebarCollapsed\(\(current\) => !current\)/);
  assert.match(app, /title=\{sidebarCollapsed \? t\.app\.sidebar\.expand : t\.app\.sidebar\.collapse\}/);
  assert.match(app, /ow-brand-card[\s\S]*ow-sidebar-toggle/);
  assert.match(app, /ow-brand-card mb-5 flex min-h-16 items-center/);
  assert.match(app, /ow-sidebar-toggle flex w-full items-center/);
  assert.match(app, /!sidebarCollapsed && <span>\{t\.app\.sidebar\.collapse\}<\/span>/);
  assert.match(app, /!sidebarCollapsed && t\.app\.tabs\[key\]/);
});

test("app shell removes the visual drag strip while keeping drag regions", () => {
  const app = readFileSync(join(root, "src", "App.tsx"), "utf8");
  const css = readFileSync(join(root, "src", "index.css"), "utf8");

  assert.equal(app.includes("ow-drag-strip"), false);
  assert.match(app, /data-tauri-drag-region/);
  assert.match(app, /startDragging/);
  assert.equal(css.includes(".ow-drag-strip"), false);
});

test("sidebar collapse labels exist in both locales", () => {
  for (const locale of ["en", "zh"]) {
    const source = readFileSync(join(root, "src", "i18n", "locales", `${locale}.ts`), "utf8");
    assert.match(source, /sidebar:\s*\{/);
    assert.match(source, /collapse:\s*"/);
    assert.match(source, /expand:\s*"/);
  }
});

test("app shell exposes first-class usage and notification tabs in navigation and routing", () => {
  const app = readFileSync(join(root, "src", "App.tsx"), "utf8");
  const tabs = readFileSync(join(root, "src", "utils", "appTabs.js"), "utf8");
  const types = readFileSync(join(root, "src", "utils", "appTabs.d.ts"), "utf8");
  const pages = readFileSync(join(root, "src", "pages", "index.ts"), "utf8");

  assert.match(tabs, /PRIMARY_APP_TABS = \["dashboard", "sessions", "usage", "commands", "notifications", "setup"\]/);
  assert.match(types, /"dashboard" \| "sessions" \| "usage" \| "commands" \| "notifications" \| "config" \| "setup"/);
  assert.match(app, /activeTab === "usage"/);
  assert.match(app, /activeTab === "notifications"/);
  assert.match(app, /<UsageBrowser \/>/);
  assert.match(app, /<NotificationSettingsPanel \/>/);
  assert.match(pages, /export \{ UsageBrowser \} from "\.\/UsageBrowser";/);
});

test("settings exposes attachment cache controls under a maintenance section", () => {
  const app = readFileSync(join(root, "src", "App.tsx"), "utf8");
  const setup = readFileSync(join(root, "src", "pages", "SetupWizard.tsx"), "utf8");
  const maintenance = readFileSync(join(root, "src", "components", "MaintenanceSettingsPanel.tsx"), "utf8");
  const components = readFileSync(join(root, "src", "components", "index.ts"), "utf8");
  const types = readFileSync(join(root, "src", "i18n", "types.ts"), "utf8");
  const zh = readFileSync(join(root, "src", "i18n", "locales", "zh.ts"), "utf8");
  const en = readFileSync(join(root, "src", "i18n", "locales", "en.ts"), "utf8");

  assert.match(app, /"maintenance"/);
  assert.match(app, /<MaintenanceSettingsPanel \/>/);
  assert.match(components, /export \{ MaintenanceSettingsPanel \}/);
  assert.equal(setup.includes("get_attachment_cache_stats"), false);
  assert.equal(setup.includes("clear_attachment_cache"), false);
  assert.match(maintenance, /get_attachment_cache_stats/);
  assert.match(maintenance, /clear_attachment_cache/);
  assert.match(types, /attachmentCacheTitle:\s*string/);
  assert.match(zh, /附件缓存/);
  assert.match(en, /Attachment Cache/);
});

test("maintenance keeps external Codex permission hook install out of the app shell", () => {
  const maintenance = readFileSync(join(root, "src", "components", "MaintenanceSettingsPanel.tsx"), "utf8");
  const service = readFileSync(join(root, "src-tauri", "src", "commands", "service.rs"), "utf8");
  const lib = readFileSync(join(root, "src-tauri", "src", "lib.rs"), "utf8");
  const types = readFileSync(join(root, "src", "i18n", "types.ts"), "utf8");
  const zh = readFileSync(join(root, "src", "i18n", "locales", "zh.ts"), "utf8");
  const en = readFileSync(join(root, "src", "i18n", "locales", "en.ts"), "utf8");

  assert.equal(maintenance.includes("install_codex_hook"), false);
  assert.equal(maintenance.includes("codexHookTitle"), false);
  assert.equal(service.includes("pub async fn install_codex_hook"), false);
  assert.equal(service.includes("--install-codex-hook"), false);
  assert.equal(service.includes("CodexHookInstall"), false);
  assert.equal(lib.includes("install_codex_hook"), false);
  assert.equal(types.includes("codexHookTitle"), false);
  assert.equal(zh.includes("Codex 权限入口"), false);
  assert.equal(en.includes("Codex Permission Entry"), false);
});

test("provider settings keeps civility mode controls sealed while rewrite is parked", () => {
  const panel = readFileSync(join(root, "src", "components", "ProviderSettingsPanel.tsx"), "utf8");
  const types = readFileSync(join(root, "src", "i18n", "types.ts"), "utf8");
  const zh = readFileSync(join(root, "src", "i18n", "locales", "zh.ts"), "utf8");
  const en = readFileSync(join(root, "src", "i18n", "locales", "en.ts"), "utf8");
  const codexPlugin = readFileSync(
    join(root, "..", "plugins", "providers", "builtin", "codex", "plugin.yaml"),
    "utf8"
  );
  const claudePlugin = readFileSync(
    join(root, "..", "plugins", "providers", "builtin", "claude", "plugin.yaml"),
    "utf8"
  );

  assert.match(panel, /const CIVILITY_MODE_SEALED = true/);
  assert.match(panel, /supportsMessageRewrite/);
  assert.match(panel, /!CIVILITY_MODE_SEALED && Boolean/);
  assert.match(panel, /set_provider_message_hook_enabled/);
  assert.match(panel, /abusive_language_normalization/);
  assert.match(panel, /texts\.civilityModeTitle/);
  assert.match(panel, /provider\?\.messageHooks\?\.abusiveLanguageNormalization\.enabled/);
  assert.equal(panel.includes("navigator.clipboard.writeText"), false);
  assert.match(types, /civilityModeTitle:\s*string/);
  assert.match(types, /civilityModeDescription:\s*string/);
  assert.match(codexPlugin, /external_cli:\s*remote_proxy/);
  assert.match(codexPlugin, /wrapper:\s*ow-codex/);
  assert.match(claudePlugin, /external_cli:\s*http_proxy/);
  assert.match(claudePlugin, /wrapper:\s*ow-claude/);
  assert.match(zh, /文明模式/);
  assert.match(en, /Civility mode/);
});

test("provider settings exposes external CLI rewrite configuration in the app", () => {
  const panel = readFileSync(join(root, "src", "components", "ProviderSettingsPanel.tsx"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");
  const i18nTypes = readFileSync(join(root, "src", "i18n", "types.ts"), "utf8");
  const zh = readFileSync(join(root, "src", "i18n", "locales", "zh.ts"), "utf8");
  const en = readFileSync(join(root, "src", "i18n", "locales", "en.ts"), "utf8");
  const rustConfig = readFileSync(join(root, "src-tauri", "src", "commands", "config.rs"), "utf8");
  const rustLib = readFileSync(join(root, "src-tauri", "src", "lib.rs"), "utf8");

  assert.match(types, /export interface ProviderExternalCliConfig/);
  assert.match(types, /externalCli:\s*ProviderExternalCliConfig;/);
  assert.match(panel, /set_provider_cli_config/);
  assert.match(panel, /externalCliUpstreamBaseUrl/);
  assert.match(panel, /externalCliLauncherWrapsClaude/);
  assert.match(panel, /supportsClaudeLauncher/);
  assert.match(panel, /providerId === "claude"/);
  assert.match(panel, /supportsClaudeLauncher\(setting\.id\)/);
  assert.match(panel, /provider\?\.capabilities\.messageRewrite\?\.externalCli/);
  assert.match(i18nTypes, /externalCliTitle:\s*string/);
  assert.match(zh, /外部 CLI/);
  assert.equal(zh.includes("外挂 CLI"), false);
  assert.equal(zh.includes("启动器会再调用 claude"), false);
  assert.match(zh, /发送前将不文明表达改写为普通表达。/);
  assert.match(zh, /启动后进入 Claude CLI/);
  assert.match(en, /External CLI/);
  assert.match(en, /Rewrite abusive language into neutral wording before sending./);
  assert.match(en, /Open Claude CLI after launcher starts/);
  assert.match(rustConfig, /pub async fn set_provider_cli_config/);
  assert.match(rustLib, /set_provider_cli_config/);
});

test("notification tab exposes split app list and plugin-defined configuration", () => {
  const app = readFileSync(join(root, "src", "App.tsx"), "utf8");
  const panel = readFileSync(join(root, "src", "components", "NotificationSettingsPanel.tsx"), "utf8");
  const components = readFileSync(join(root, "src", "components", "index.ts"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");
  const i18nTypes = readFileSync(join(root, "src", "i18n", "types.ts"), "utf8");
  const zh = readFileSync(join(root, "src", "i18n", "locales", "zh.ts"), "utf8");
  const en = readFileSync(join(root, "src", "i18n", "locales", "en.ts"), "utf8");

  assert.match(app, /"notifications"/);
  assert.match(app, /<NotificationSettingsPanel \/>/);
  assert.match(app, /grid-cols-5/);
  assert.equal(app.includes('["notifications", "Notifications"]'), false);
  assert.match(components, /export \{ NotificationSettingsPanel \}/);
  assert.match(types, /export interface NotificationChannelMetadata/);
  assert.match(types, /icon\?: ProviderIconMetadata \| null;/);
  assert.match(types, /export interface NotificationSetupGuide/);
  assert.match(types, /setupGuide\?: NotificationSetupGuide \| null;/);
  assert.match(panel, /get_notification_channels/);
  assert.match(panel, /set_notification_channel_enabled/);
  assert.match(panel, /set_notification_channel_config/);
  assert.match(panel, /srcDoc=\{guideHtml\}/);
  assert.match(panel, /sandbox=""/);
  assert.match(panel, /notifications\.guideTab/);
  assert.equal(panel.includes("write_env_field"), false);
  assert.equal(panel.includes("read_env_field"), false);
  assert.match(panel, /useI18n/);
  assert.match(panel, /notifications\.channelsTitle/);
  assert.equal(panel.includes("Supported Apps"), false);
  assert.equal(panel.includes("Save configuration"), false);
  assert.equal((panel.match(/set_notification_channel_enabled/g) ?? []).length, 1);
  assert.equal((panel.match(/notifications\.enableChannel/g) ?? []).length, 1);
  assert.match(i18nTypes, /notifications:\s*\{/);
  assert.match(zh, /通知渠道/);
  assert.match(zh, /文件助手/);
  assert.match(zh, /私聊/);
  assert.match(zh, /群聊/);
  assert.match(zh, /接收人/);
  assert.match(zh, /通过 POPO 发送简短任务通知。/);
  assert.match(en, /Notification channels/);
  assert.match(panel, /ChannelIcon/);
  assert.match(panel, /settingsFields/);
  assert.match(panel, /setupGuide/);
  assert.match(panel, /service_restart/);
});

test("dashboard renders provider icons from provider metadata", () => {
  const dashboard = readFileSync(join(root, "src", "pages", "Dashboard.tsx"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");

  assert.match(types, /export interface ProviderIconMetadata/);
  assert.match(types, /icon\?: ProviderIconMetadata \| null;/);
  assert.match(dashboard, /provider\.icon\?\.url\?\.trim\(\)/);
  assert.match(dashboard, /<ProviderIcon provider=\{provider\} \/>/);
  assert.equal(dashboard.includes("function ProviderIcon()"), false);
});
