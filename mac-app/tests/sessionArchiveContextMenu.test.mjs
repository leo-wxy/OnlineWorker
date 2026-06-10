import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("session browser exposes provider-backed archive actions from visible and context menus", () => {
  const sessionBrowser = readFileSync(join(root, "src", "pages", "SessionBrowser.tsx"), "utf8");
  const api = readFileSync(join(root, "src", "components", "session-browser", "api.ts"), "utf8");
  const archiveUi = readFileSync(join(root, "src", "components", "session-browser", "archive.tsx"), "utf8");
  const navigation = readFileSync(join(root, "src", "components", "session-browser", "navigation.tsx"), "utf8");
  const workspaceActions = readFileSync(join(root, "src", "components", "session-browser", "workspaceActions.tsx"), "utf8");
  const terminalCommands = readFileSync(join(root, "src-tauri", "src", "commands", "terminal.rs"), "utf8");
  const tauriLib = readFileSync(join(root, "src-tauri", "src", "lib.rs"), "utf8");

  assert.match(api, /export async function archiveProviderSession\(/);
  assert.match(api, /invoke\("archive_provider_session"/);
  assert.match(api, /providerId,\s*[\s\S]*sessionId,\s*[\s\S]*workspaceDir:\s*workspaceDir \?\? null,\s*[\s\S]*sessionTitle:\s*sessionTitle \?\? null/);

  assert.match(sessionBrowser, /archiveSessionWithFeedback,/);
  assert.match(sessionBrowser, /invoke<TaskBoardState>\("get_task_board_state"\)/);
  assert.match(sessionBrowser, /pin_task_board_session/);
  assert.match(sessionBrowser, /unpin_task_board_session/);
  assert.match(sessionBrowser, /SessionActionMenu,/);
  assert.match(sessionBrowser, /<SessionListPanel/);
  assert.match(sessionBrowser, /pinnedSessionIds=\{pinnedSessionIds\}/);
  assert.match(sessionBrowser, /onTogglePinSession=\{\(session\) => void handleTogglePinSession\(session\)\}/);
  assert.match(sessionBrowser, /onOpenContextMenu=\{openSessionContextMenu\}/);
  assert.match(sessionBrowser, /onOpenActionMenu=\{openSessionActionMenu\}/);
  assert.match(sessionBrowser, /WorkspaceActionMenu,/);
  assert.match(sessionBrowser, /const \[workspaceContextMenu,\s*setWorkspaceContextMenu\] = useState<WorkspaceActionMenuState \| null>\(null\);/);
  assert.match(sessionBrowser, /onOpenWorkspaceContextMenu=\{openWorkspaceContextMenu\}/);
  assert.match(sessionBrowser, /invoke\("open_terminal",\s*\{\s*workspacePath:\s*workspace\s*\}\)/);
  assert.match(sessionBrowser, /invoke\("open_finder",\s*\{\s*workspacePath:\s*workspace\s*\}\)/);
  assert.match(sessionBrowser, /navigator\.clipboard\.writeText\(workspace\)/);
  assert.match(navigation, /ArchiveNoticeBanner/);
  assert.match(navigation, /onOpenWorkspaceContextMenu\?: \(event: MouseEvent<HTMLElement>, workspace: string\) => void;/);
  assert.match(navigation, /onContextMenu=\{\(event\) => onOpenWorkspaceContextMenu\?\.\(event, ws\)\}/);
  assert.match(navigation, /aria-pressed=\{isPinned\}/);
  assert.match(navigation, /aria-label=\{isPinned \? labels\.unpinSession : labels\.pinSession\}/);
  assert.match(navigation, /onTogglePinSession\(session\)/);
  assert.match(navigation, /onContextMenu=\{\(event\) => onOpenContextMenu\(event, session\)\}/);
  assert.match(navigation, /onOpenActionMenu\(event, session\)/);
  assert.match(navigation, /aria-label=\{labels\.sessionActions\}/);
  assert.match(navigation, /role="button"/);
  assert.match(
    archiveUi,
    /await archiveProviderSession\(session\.type,\s*session\.id,\s*session\.workspace,\s*session\.title\)/,
  );
  assert.match(archiveUi, /role="menu"/);
  assert.match(archiveUi, /role="menuitem"/);
  assert.match(archiveUi, /tone: "error"/);
  assert.match(sessionBrowser, /setArchiveNotice\(nextNotice\)/);
  assert.doesNotMatch(sessionBrowser, /session\.archived\s*=\s*true/);
  assert.match(workspaceActions, /export function WorkspaceActionMenu/);
  assert.match(workspaceActions, /labels\.openInTerminal/);
  assert.match(workspaceActions, /labels\.openInFinder/);
  assert.match(workspaceActions, /labels\.copyPath/);
  assert.match(workspaceActions, /role="menu"/);
  assert.match(workspaceActions, /role="menuitem"/);
  assert.match(terminalCommands, /pub async fn open_finder\(workspace_path: String\) -> Result<\(\), String>/);
  assert.match(terminalCommands, /\.args\(\["-a", "Finder", normalized_workspace\]\)/);
  assert.match(tauriLib, /use commands::terminal::\{open_codex_tui_host_terminal, open_finder, open_terminal\};/);
  assert.match(tauriLib, /open_finder,/);
});

test("session archive strings exist in both locales and the i18n contract", () => {
  const types = readFileSync(join(root, "src", "i18n", "types.ts"), "utf8");
  assert.match(types, /sessionActions: string;/);
  assert.match(types, /openWorkspaceInTerminal: string;/);
  assert.match(types, /openWorkspaceInFinder: string;/);
  assert.match(types, /copyWorkspacePath: string;/);
  assert.match(types, /alreadyArchived: string;/);
  assert.match(types, /pinSession: string;/);
  assert.match(types, /unpinSession: string;/);
  assert.match(types, /archiveSession: string;/);
  assert.match(types, /archivingSession: string;/);
  assert.match(types, /archiveSucceeded: string;/);
  assert.match(types, /archiveFailed: \(error: string\) => string;/);

  for (const locale of ["en", "zh"]) {
    const source = readFileSync(join(root, "src", "i18n", "locales", `${locale}.ts`), "utf8");
    assert.match(source, /sessionActions:/);
    assert.match(source, /openWorkspaceInTerminal:/);
    assert.match(source, /openWorkspaceInFinder:/);
    assert.match(source, /copyWorkspacePath:/);
    assert.match(source, /alreadyArchived:/);
    assert.match(source, /pinSession:/);
    assert.match(source, /unpinSession:/);
    assert.match(source, /archiveSession:/);
    assert.match(source, /archivingSession:/);
    assert.match(source, /archiveSucceeded:/);
    assert.match(source, /archiveFailed:\s*\(error: string\)\s*=>/);
  }

  const zh = readFileSync(join(root, "src", "i18n", "locales", "zh.ts"), "utf8");
  assert.match(zh, /openWorkspaceInTerminal:\s*"使用终端打开"/);
  assert.match(zh, /openWorkspaceInFinder:\s*"使用Finder打开"/);
  assert.match(zh, /copyWorkspacePath:\s*"拷贝路径"/);
});
