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
  assert.match(app, /!sidebarCollapsed && \(/);
  assert.match(app, /<span className="truncate">\{t\.app\.tabs\[key\]\}<\/span>/);
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

test("app shell exposes first-class task, usage, ai, and notification tabs in navigation and routing", () => {
  const app = readFileSync(join(root, "src", "App.tsx"), "utf8");
  const tabs = readFileSync(join(root, "src", "utils", "appTabs.js"), "utf8");
  const types = readFileSync(join(root, "src", "utils", "appTabs.d.ts"), "utf8");
  const pages = readFileSync(join(root, "src", "pages", "index.ts"), "utf8");
  const components = readFileSync(join(root, "src", "components", "index.ts"), "utf8");

  assert.match(tabs, /PRIMARY_APP_TABS = \["dashboard", "tasks", "sessions", "usage", "ai", "commands", "notifications", "setup"\]/);
  assert.match(types, /"dashboard" \| "tasks" \| "sessions" \| "usage" \| "ai" \| "commands" \| "notifications" \| "config" \| "setup"/);
  assert.match(app, /activeTab === "tasks"/);
  assert.match(app, /activeTab === "usage"/);
  assert.match(app, /activeTab === "ai"/);
  assert.match(app, /activeTab === "notifications"/);
  assert.match(app, /<TaskBoard[\s\S]*sessionActivities=\{taskBoardActivities\}/);
  assert.match(app, /sessionActivities=\{taskBoardActivities\}/);
  assert.match(app, /<SessionBrowser[\s\S]*openTarget=\{sessionOpenTarget\}[\s\S]*taskBoardActivities=\{taskBoardActivities\}[\s\S]*active=\{activeTab === "sessions"\}[\s\S]*\/>/);
  assert.match(app, /activeTab === "sessions" \? "" : "hidden"/);
  assert.match(app, /taskAttentionCount > 0/);
  assert.match(app, /status === "needs_attention"/);
  assert.equal(app.includes("attentionKind.length > 0"), false);
  assert.match(app, /<UsageBrowser \/>/);
  assert.match(app, /<AiSettingsPanel \/>/);
  assert.match(app, /<NotificationSettingsPanel \/>/);
  assert.match(components, /export \{ AiSettingsPanel \}/);
  assert.match(pages, /export \{ TaskBoard \} from "\.\/TaskBoard";/);
  assert.match(pages, /export \{ UsageBrowser \} from "\.\/UsageBrowser";/);
});

test("task board keeps cached provider summaries and uses force refresh only on explicit reload", () => {
  const taskBoard = readFileSync(join(root, "src", "pages", "TaskBoard.tsx"), "utf8");
  const sessionData = readFileSync(join(root, "src", "components", "session-browser", "sessionData.ts"), "utf8");

  assert.match(taskBoard, /readCachedProviderSessionSnapshotRows/);
  assert.match(taskBoard, /writeCachedProviderSessionSnapshot/);
  assert.match(taskBoard, /forceProviderRefresh\?: boolean/);
  assert.match(taskBoard, /await fetchProviderSessions\(provider\.id, \{ forceRefresh: forceProviderRefresh \}\)/);
  assert.match(taskBoard, /const hasHydratedProviderSessionsRef = useRef\(false\);/);
  assert.match(taskBoard, /await refresh\(\{ includeActivities: true \}\);/);
  assert.match(taskBoard, /if \(cancelled \|\| hasHydratedProviderSessionsRef\.current\) \{\s*return;\s*\}/s);
  assert.match(taskBoard, /await refresh\(\{ includeActivities: false, forceProviderRefresh: true \}\);/);
  assert.equal(taskBoard.includes("if (loading || hasHydratedProviderSessionsRef.current)"), false);
  assert.match(taskBoard, /onClick=\{\(\) => void refresh\(\{ includeActivities: true, forceProviderRefresh: true \}\)\}/);
  assert.match(taskBoard, /await refresh\(\{ includeActivities: true, forceProviderRefresh: true \}\);/);
  assert.match(sessionData, /const providerSessionSnapshotCache = new Map/);
  assert.match(sessionData, /export function readCachedProviderSessionSnapshotRows/);
  assert.match(sessionData, /export function writeCachedProviderSessionSnapshot/);
});

test("session browser loads provider sessions only when the tab is active and keeps first visible load cache-friendly", () => {
  const sessionBrowser = readFileSync(join(root, "src", "pages", "SessionBrowser.tsx"), "utf8");
  const navigation = readFileSync(join(root, "src", "components", "session-browser", "navigation.tsx"), "utf8");

  assert.match(sessionBrowser, /const activatedProvidersRef = useRef<Set<ProviderFilter>>\(new Set\(\)\);/);
  assert.match(sessionBrowser, /const loadingProvidersRef = useRef<Set<ProviderFilter>>\(new Set\(\)\);/);
  assert.match(sessionBrowser, /const emptyForceRefreshAttemptsRef = useRef<Map<ProviderFilter, number>>\(new Map\(\)\);/);
  assert.match(sessionBrowser, /const \[providerReloadTick,\s*setProviderReloadTick\] = useState\(0\);/);
  assert.match(sessionBrowser, /const retryTimerRef = useRef<number \| null>\(null\);/);
  assert.doesNotMatch(sessionBrowser, /const shouldSeedCachedSessions = true;/);
  assert.match(sessionBrowser, /if \(cachedSessions\.length > 0\) \{\s*loadedProvidersRef\.current\.add\(provider\);/s);
  assert.match(sessionBrowser, /loadingProvidersRef\.current\.add\(provider\);/);
  assert.match(sessionBrowser, /setLoading\(loadingProvidersRef\.current\.size > 0\);/);
  assert.match(sessionBrowser, /const providerListReady = loadedProvidersRef\.current\.has\(providerFilter\);/);
  assert.match(sessionBrowser, /const waitingForProviderList = useMemo/);
  assert.match(sessionBrowser, /if \(!providerListReady && sessions\.length === 0\) \{\s*return sessions;\s*\}/s);
  assert.match(sessionBrowser, /resolveSessionSnapshotUpdate\(cachedSessions, normalizedSessions, \{/);
  assert.match(sessionBrowser, /emptyRetryBudget: options\?\.forceRefresh && !acceptEmptySnapshot \? 1 : 0,/);
  assert.match(sessionBrowser, /window\.setTimeout\(\(\) => \{\s*setProviderReloadTick\(\(current\) => current \+ 1\);\s*\}, 750\)/s);
  assert.match(sessionBrowser, /if \(!active \|\| !providerFilter\) \{\s*return;\s*\}/s);
  assert.match(sessionBrowser, /const hasLoadedProvider = loadedProvidersRef\.current\.has\(providerFilter\);/);
  assert.match(sessionBrowser, /const hasActivatedProvider = activatedProvidersRef\.current\.has\(providerFilter\);/);
  assert.match(sessionBrowser, /const loaded = await loadProvider\(providerFilter, \{\s*force: true,\s*forceRefresh: false,\s*\}\);/s);
  assert.match(sessionBrowser, /if \(loaded\) \{\s*activatedProvidersRef\.current\.add\(providerFilter\);\s*\}/s);
  assert.match(sessionBrowser, /\}, \[active, loadProvider, providerFilter, providerReloadTick\]\);/);
  assert.match(sessionBrowser, /if \(!active \|\| !openTarget \|\| openTarget\.providerId !== providerFilter\) \{\s*return;\s*\}/s);
  assert.match(sessionBrowser, /void loadProvider\(openTarget\.providerId, \{\s*force: true,\s*forceRefresh: true,\s*\}\);/s);
  assert.match(sessionBrowser, /await loadProvider\(previousSession\.type, \{\s*force: true,\s*forceRefresh: true,\s*\}\);/s);
  assert.match(sessionBrowser, /acceptEmptySnapshot: true,/);
  assert.match(navigation, /loading = false/);
  assert.match(navigation, /\{loading && workspaces\.length === 0 \? \(\s*<StatePanel message=\{noSessionsLabel\} \/>/s);
  assert.match(navigation, /\{loading && sessions\.length === 0 \? \(\s*<StatePanel message=\{labels\.noSessions\} \/>/s);
});

test("session navigation keeps populated lists visible during background provider refresh", () => {
  const navigation = readFileSync(join(root, "src", "components", "session-browser", "navigation.tsx"), "utf8");

  assert.match(navigation, /loading && workspaces\.length === 0/);
  assert.match(navigation, /loading && sessions\.length === 0/);
  assert.doesNotMatch(navigation, /\{loading \? \(\s*<StatePanel message=\{noSessionsLabel\} \/>/s);
  assert.doesNotMatch(navigation, /\{loading \? \(\s*<StatePanel message=\{labels\.noSessions\} \/>/s);
});

test("ai settings uses fixed service cards and scenario service selection", () => {
  const panel = readFileSync(join(root, "src", "components", "AiSettingsPanel.tsx"), "utf8");
  const utils = readFileSync(join(root, "src", "components", "ai-settings", "utils.ts"), "utf8");
  const serviceEditor = readFileSync(join(root, "src", "components", "ai-settings", "AiServiceEditor.tsx"), "utf8");
  const scenarioEditor = readFileSync(join(root, "src", "components", "ai-settings", "AiScenarioEditor.tsx"), "utf8");
  const sidebar = readFileSync(join(root, "src", "components", "ai-settings", "AiSettingsSidebar.tsx"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");
  const i18nTypes = readFileSync(join(root, "src", "i18n", "types.ts"), "utf8");
  const zh = readFileSync(join(root, "src", "i18n", "locales", "zh.ts"), "utf8");
  const en = readFileSync(join(root, "src", "i18n", "locales", "en.ts"), "utf8");

  assert.match(panel, /<AiSettingsSidebar/);
  assert.match(panel, /<AiServiceEditor/);
  assert.match(panel, /<AiScenarioEditor/);
  assert.match(panel, /get_ai_config/);
  assert.match(panel, /set_ai_config/);
  assert.match(panel, /test_ai_service_connection/);
  assert.match(utils, /function serviceTitle/);
  assert.match(utils, /service\.label \|\| service\.name \|\| service\.id/);
  assert.match(utils, /service\.description \|\| labels\.customServiceDescription/);
  assert.match(panel, /service\?\.pluginOwned/);
  assert.match(serviceEditor, /labels\.enableService/);
  assert.match(scenarioEditor, /labels\.enableScenario/);
  assert.match(panel, /const setServiceEnabled = /);
  assert.match(panel, /const setScenarioEnabled = /);
  assert.match(serviceEditor, /onChange=\{\(checked\) => onSetEnabled\(service\.id, checked\)\}/);
  assert.match(scenarioEditor, /onChange=\{\(checked\) => onSetEnabled\(scenario\.id, checked\)\}/);
  assert.match(scenarioEditor, /<select[\s\S]*services\.map/);
  assert.match(scenarioEditor, /model:\s*""/);
  assert.match(scenarioEditor, /selectedService\?\.defaultModel/);
  assert.match(scenarioEditor, /scenarioLimitEntries/);
  assert.match(panel, /updateScenarioLimit/);
  assert.match(utils, /labels\.limitLabels/);
  assert.match(sidebar, /serviceBadge/);
  assert.match(sidebar, /scenarioBadge/);
  assert.equal(`${panel}${utils}${serviceEditor}${scenarioEditor}${sidebar}`.includes("addService"), false);
  assert.equal(`${panel}${utils}${serviceEditor}${scenarioEditor}${sidebar}`.includes("labels.protocol"), false);
  assert.equal(`${panel}${utils}${serviceEditor}${scenarioEditor}${sidebar}`.includes("labels.apiKeyEnv"), false);
  assert.equal(`${panel}${utils}${serviceEditor}${scenarioEditor}${sidebar}`.includes("apiKeySource"), false);
  assert.equal(`${panel}${utils}${serviceEditor}${scenarioEditor}${sidebar}`.includes("selectedScenario.model"), false);
  assert.match(types, /apiKey\?: string \| null;/);
  assert.match(i18nTypes, /effectiveModel:\s*string/);
  assert.match(zh, /内置服务由插件清单提供/);
  assert.match(zh, /场景只选择一个已配置服务/);
  assert.match(en, /Built-in services come from plugin manifests/);
  assert.match(en, /A scenario selects one configured service/);
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
  assert.match(types, /civilityModeTitle:\s*string/);
  assert.match(types, /civilityModeDescription:\s*string/);
  assert.match(codexPlugin, /external_cli:\s*remote_proxy/);
  assert.match(codexPlugin, /wrapper:\s*ow-codex/);
  assert.match(claudePlugin, /external_cli:\s*http_proxy/);
  assert.match(claudePlugin, /wrapper:\s*ow-claude/);
  assert.match(zh, /文明模式/);
  assert.match(en, /Civility mode/);
});

test("provider settings exposes discovered hidden extensions with icons and a visible hint", () => {
  const panel = readFileSync(join(root, "src", "components", "ProviderSettingsPanel.tsx"), "utf8");
  const types = readFileSync(join(root, "src", "i18n", "types.ts"), "utf8");
  const zh = readFileSync(join(root, "src", "i18n", "locales", "zh.ts"), "utf8");
  const en = readFileSync(join(root, "src", "i18n", "locales", "en.ts"), "utf8");

  assert.match(panel, /function ProviderIcon/);
  assert.match(panel, /provider\?\.icon\?\.url\?\.trim\(\)/);
  assert.match(panel, /texts\.hiddenByDefault/);
  assert.match(panel, /texts\.hiddenByDefaultHint/);
  assert.match(types, /hiddenByDefault:\s*string/);
  assert.match(types, /hiddenByDefaultHint:\s*string/);
  assert.match(zh, /默认隐藏/);
  assert.match(en, /Hidden by default/);
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
  assert.match(panel, /navigator\.clipboard\.writeText/);
  assert.equal(panel.includes("externalCliUpstreamBaseUrl"), false);
  assert.equal(panel.includes("draft.upstreamBaseUrl"), false);
  assert.match(panel, /externalCliLaunchesManagedChildCli/);
  assert.match(panel, /supportsLaunchMethods/);
  assert.match(panel, /provider\?\.capabilities\.launchMethods === true/);
  assert.match(panel, /supportsExternalCliAuthConfig/);
  assert.match(panel, /supportsExternalCliLauncherWrap/);
  assert.match(panel, /primaryProviderSettings\(providers\)/);
  assert.match(panel, /extensionProviderSettings\(providers\)/);
  assert.match(panel, /provider\?\.capabilities\.messageRewrite\?\.externalCli/);
  assert.match(panel, /managedRemoteProxyAlias/);
  assert.match(types, /proxyAlias\?:\s*string \| null/);
  assert.equal(panel.includes("CODEX_REMOTE_PROXY_ALIAS"), false);
  assert.equal(panel.includes("codexR"), false);
  assert.match(types, /launchMethods:\s*boolean/);
  assert.match(types, /launchMethods\?:\s*ProviderLaunchMethodConfig\[\]/);
  assert.match(types, /export interface ProviderDiscoveryMetadata/);
  assert.match(types, /discovery\?:\s*ProviderDiscoveryMetadata/);
  assert.match(i18nTypes, /cliConfigTitle:\s*string/);
  assert.match(i18nTypes, /launchMethodCommands:\s*string/);
  assert.match(i18nTypes, /externalCliProxyAliasTitle:\s*string/);
  assert.match(i18nTypes, /externalCliProxyAliasDescription:\s*string/);
  assert.match(i18nTypes, /externalCliAuthToken:\s*string/);
  assert.match(i18nTypes, /externalCliBaseUrl:\s*string/);
  assert.match(i18nTypes, /externalCliModel:\s*string/);
  assert.equal(i18nTypes.includes("externalCliUpstreamBaseUrl"), false);
  assert.equal(i18nTypes.includes("externalCliCodexAliasTitle"), false);
  assert.equal(i18nTypes.includes("claudeAuthToken"), false);
  assert.equal(i18nTypes.includes("claudeBaseUrl"), false);
  assert.equal(i18nTypes.includes("claudeModel"), false);
  assert.match(zh, /CLI 配置/);
  assert.match(zh, /启动命令候选/);
  assert.equal(zh.includes("上游 Base URL"), false);
  assert.equal(zh.includes("外挂 CLI"), false);
  assert.equal(zh.includes("启动器会再调用 claude"), false);
  assert.match(zh, /发送前将不文明表达改写为普通表达。/);
  assert.match(zh, /启动后进入受管子 CLI/);
  assert.match(en, /CLI configuration/);
  assert.match(en, /Launch command candidates/);
  assert.equal(en.includes("Upstream Base URL"), false);
  assert.match(en, /Rewrite abusive language into neutral wording before sending./);
  assert.match(en, /Open the managed child CLI after launcher starts/);
  assert.match(rustConfig, /pub async fn set_provider_cli_config/);
  assert.match(rustLib, /set_provider_cli_config/);
});

test("provider settings exposes lightweight provider configuration validation", () => {
  const panel = readFileSync(join(root, "src", "components", "ProviderSettingsPanel.tsx"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");
  const i18nTypes = readFileSync(join(root, "src", "i18n", "types.ts"), "utf8");
  const zh = readFileSync(join(root, "src", "i18n", "locales", "zh.ts"), "utf8");
  const en = readFileSync(join(root, "src", "i18n", "locales", "en.ts"), "utf8");
  const rustConfig = readFileSync(join(root, "src-tauri", "src", "commands", "config.rs"), "utf8");
  const rustLib = readFileSync(join(root, "src-tauri", "src", "lib.rs"), "utf8");

  assert.match(panel, /validate_provider_config/);
  assert.match(panel, /ProviderValidationReport/);
  assert.match(panel, /validationReports/);
  assert.match(panel, /clearProviderValidationReport/);
  assert.match(panel, /disabled=\{Boolean\(validatingProviderId\)\}/);
  assert.match(panel, /texts\.validateConfig/);
  assert.match(panel, /texts\.validatingConfig/);
  assert.match(panel, /report\.checks\.map/);
  assert.match(types, /export interface ProviderValidationReport/);
  assert.match(types, /export interface ProviderValidationCheck/);
  assert.match(i18nTypes, /validateConfig:\s*string/);
  assert.match(i18nTypes, /validationOk:\s*string/);
  assert.match(i18nTypes, /validationFailed:\s*string/);
  assert.match(zh, /验证配置/);
  assert.match(zh, /配置可用/);
  assert.match(en, /Validate config/);
  assert.match(en, /Configuration ready/);
  assert.match(rustConfig, /pub async fn validate_provider_config/);
  assert.match(rustLib, /validate_provider_config/);
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
  assert.match(zh, /通知渠道/);
  assert.match(zh, /通过独立 Telegram Bot 发送简短任务通知。/);
  assert.match(en, /Notification channels/);
  assert.match(panel, /ChannelIcon/);
  assert.match(panel, /settingsFields/);
  assert.match(panel, /setupGuide/);
  assert.match(panel, /service_restart/);
});

test("dashboard renders provider icons from provider metadata", () => {
  const dashboard = readFileSync(join(root, "src", "pages", "Dashboard.tsx"), "utf8");
  const providerList = readFileSync(
    join(root, "src", "components", "dashboard", "ProviderStatusList.tsx"),
    "utf8"
  );
  const providerIcon = readFileSync(
    join(root, "src", "components", "dashboard", "ProviderIcon.tsx"),
    "utf8"
  );
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");

  assert.match(types, /export interface ProviderIconMetadata/);
  assert.match(types, /icon\?: ProviderIconMetadata \| null;/);
  assert.match(providerIcon, /provider\.icon\?\.url\?\.trim\(\)/);
  assert.match(providerList, /<ProviderIcon provider=\{provider\} \/>/);
  assert.match(providerList, /function parseProviderStatusItems/);
  assert.match(providerList, /function formatStatusBadgeText/);
  assert.match(providerList, /rounded-2xl px-3 py-2\.5/);
  assert.match(providerList, /break-words/);
  assert.equal(providerList.includes("truncate text-sm font-mono"), false);
  assert.equal(providerList.includes(" · "), false);
  assert.equal(dashboard.includes("function ProviderIcon()"), false);
});

test("task board listens to activity stream without fallback polling", () => {
  const app = readFileSync(join(root, "src", "App.tsx"), "utf8");
  const taskBoard = readFileSync(join(root, "src", "pages", "TaskBoard.tsx"), "utf8");
  const taskModel = readFileSync(join(root, "src", "utils", "taskBoard.js"), "utf8");
  const taskModelTypes = readFileSync(join(root, "src", "utils", "taskBoard.d.ts"), "utf8");
  const lib = readFileSync(join(root, "src-tauri", "src", "lib.rs"), "utf8");
  const taskBoardState = readFileSync(join(root, "src-tauri", "src", "commands", "task_board_state.rs"), "utf8");

  assert.match(taskBoard, /onClick=\{\(\) => void refresh\(\{ includeActivities: true, forceProviderRefresh: true \}\)\}/);
  assert.match(app, /start_task_board_activity_stream/);
  assert.match(taskModelTypes, /export interface TaskBoardActivityStreamEvent/);
  assert.match(taskModel, /export function taskBoardSessionKey/);
  assert.match(taskModel, /export function upsertTaskBoardActivity/);
  assert.match(taskModel, /export function removeTaskBoardActivity/);
  assert.match(taskBoard, /sharedSessionActivities !== undefined/);
  assert.match(taskBoard, /onSessionActivitiesChange\?/);
  assert.match(taskBoard, /const activity = event\.activity;/);
  assert.match(taskBoard, /setLocalSessionActivities\(\(current\) => upsertTaskBoardActivity\(current, activity\)\)/);
  assert.match(taskBoard, /event\.kind === "remove"/);
  assert.match(taskBoard, /setLocalSessionActivities\(\(current\) => removeTaskBoardActivity\(current, event\.providerId!, event\.sessionId!\)\)/);
  assert.match(taskBoard, /refresh\(\{ includeActivities: true \}\)/);
  assert.match(taskBoard, /setLoading\(false\);/);
  assert.equal(taskBoard.includes("window.setInterval(() => {\n      void refresh();"), false);
  assert.match(taskBoard, /setInterval\(\(\) => setNowMs\(Date\.now\(\)\), 30_000\)/);
  assert.equal(app.includes("interface TaskBoardActivityStreamEvent"), false);
  assert.equal(taskBoard.includes("interface TaskBoardActivityStreamEvent"), false);
  assert.match(app, /let activeStreamId: number \| null = null/);
  assert.match(app, /invoke<number>\("start_task_board_activity_stream", \{ channel \}\)/);
  assert.match(app, /invoke\("stop_task_board_activity_stream", \{ streamId: activeStreamId \}\)/);
  assert.match(taskBoardState, /session_activity_stream/);
  assert.match(taskBoardState, /fn begin_task_board_activity_stream\(\) -> u64/);
  assert.match(taskBoardState, /fn stop_task_board_activity_stream_id\(stream_id: u64\)/);
  assert.match(taskBoardState, /while task_board_activity_stream_is_active\(stream_id\)/);
  assert.match(taskBoardState, /std::thread::sleep\(reconnect_delay\)/);
  assert.match(lib, /start_task_board_activity_stream/);
  assert.match(lib, /stop_task_board_activity_stream/);
});

test("task board does not render approval buttons for external mirrored CLI approvals", () => {
  const taskBoard = readFileSync(join(root, "src", "pages", "TaskBoard.tsx"), "utf8");
  const taskModelTypes = readFileSync(join(root, "src", "utils", "taskBoard.d.ts"), "utf8");
  const taskModel = readFileSync(join(root, "src", "utils", "taskBoard.js"), "utf8");

  assert.match(taskBoard, /!task\.mirroredOnly/);
  assert.match(taskModelTypes, /mirroredOnly\?: boolean;/);
  assert.match(taskModelTypes, /mirroredOnly: boolean;/);
  assert.match(taskModel, /mirroredOnly: activity\.mirroredOnly === true/);
});

test("task board clamps activity preview without covering card footer", () => {
  const taskBoard = readFileSync(join(root, "src", "pages", "TaskBoard.tsx"), "utf8");

  assert.match(taskBoard, /WebkitLineClamp:\s*3/);
  assert.match(taskBoard, /maxHeight:\s*"3\.75rem"/);
  assert.equal(taskBoard.includes("line-clamp-3 min-h-[4.5rem]"), false);
  assert.match(taskBoard, /mt-auto flex items-center justify-between/);
});

test("task board pinned cards expose an explicit unfollow action", () => {
  const taskBoard = readFileSync(join(root, "src", "pages", "TaskBoard.tsx"), "utf8");

  assert.match(taskBoard, /const pinLabel = task\.pinned \? t\.taskBoard\.unpin : t\.taskBoard\.pin/);
  assert.match(taskBoard, /const showPinText = task\.pinned && tone === "pinned"/);
  assert.match(taskBoard, /aria-pressed=\{task\.pinned\}/);
  assert.match(taskBoard, /aria-label=\{pinLabel\}/);
  assert.match(taskBoard, /<span className="text-\[11px\] font-semibold">\{pinLabel\}<\/span>/);
  assert.match(taskBoard, /task\.pinned \? "unpin_task_board_session" : "pin_task_board_session"/);
  assert.equal(taskBoard.includes("hide_task_board_session"), false);
  assert.equal(taskBoard.includes("removeFromBoard"), false);
});

test("task board hydrates previews for pinned idle sessions", () => {
  const taskBoard = readFileSync(join(root, "src", "pages", "TaskBoard.tsx"), "utf8");
  const taskModel = readFileSync(join(root, "src", "utils", "taskBoard.js"), "utf8");

  assert.match(taskBoard, /async function hydrateTaskBoardSessionPreviews/);
  assert.match(taskBoard, /const PINNED_PREVIEW_HYDRATION_LIMIT = 12/);
  assert.match(taskModel, /export function collectTaskBoardPreviewHydrationPlan/);
  assert.match(taskModel, /\.slice\(0, pinnedLimit\)/);
  assert.match(taskModel, /\.slice\(0, lowSignalLimit\)/);
  assert.match(taskBoard, /readSessionLastMessageWithTimeout\(session\)/);
  assert.match(taskBoard, /const pinnedKeys = new Set\(plan\.pinnedKeys\)/);
  assert.match(taskBoard, /raw:\s*\{\s*\.\.\.\(session\.raw \?\? \{\}\),\s*lastMessage,/);
  assert.match(taskBoard, /void hydrateTaskBoardSessionPreviews\(flatSessions, nextTaskBoardState\)/);
  assert.match(taskBoard, /const key = taskBoardSessionKey\(session\.type, session\.id\)/);
  assert.match(taskBoard, /setSessions\(\(current\) => mergeSessionListSnapshot\(current, hydratedSessions\)\)/);
});
