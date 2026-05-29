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

  assert.match(api, /export async function archiveProviderSession\(/);
  assert.match(api, /invoke\("archive_provider_session"/);
  assert.match(api, /providerId,\s*[\s\S]*sessionId,\s*[\s\S]*workspaceDir:\s*workspaceDir \?\? null,\s*[\s\S]*sessionTitle:\s*sessionTitle \?\? null/);

  assert.match(sessionBrowser, /archiveSessionWithFeedback,/);
  assert.match(sessionBrowser, /SessionActionMenu,/);
  assert.match(sessionBrowser, /<SessionListPanel/);
  assert.match(sessionBrowser, /onOpenContextMenu=\{openSessionContextMenu\}/);
  assert.match(sessionBrowser, /onOpenActionMenu=\{openSessionActionMenu\}/);
  assert.match(navigation, /ArchiveNoticeBanner/);
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
});

test("session archive strings exist in both locales and the i18n contract", () => {
  const types = readFileSync(join(root, "src", "i18n", "types.ts"), "utf8");
  assert.match(types, /sessionActions: string;/);
  assert.match(types, /alreadyArchived: string;/);
  assert.match(types, /archiveSession: string;/);
  assert.match(types, /archivingSession: string;/);
  assert.match(types, /archiveSucceeded: string;/);
  assert.match(types, /archiveFailed: \(error: string\) => string;/);

  for (const locale of ["en", "zh"]) {
    const source = readFileSync(join(root, "src", "i18n", "locales", `${locale}.ts`), "utf8");
    assert.match(source, /sessionActions:/);
    assert.match(source, /alreadyArchived:/);
    assert.match(source, /archiveSession:/);
    assert.match(source, /archivingSession:/);
    assert.match(source, /archiveSucceeded:/);
    assert.match(source, /archiveFailed:\s*\(error: string\)\s*=>/);
  }
});
