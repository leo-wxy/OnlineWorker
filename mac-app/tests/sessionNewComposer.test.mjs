import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("new session opens an in-memory composer instead of creating an app-state session", () => {
  const sessionBrowser = readFileSync(join(root, "src", "pages", "SessionBrowser.tsx"), "utf8");
  const genericChat = readFileSync(
    join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"),
    "utf8",
  );
  const api = readFileSync(join(root, "src", "components", "session-browser", "api.ts"), "utf8");

  assert.doesNotMatch(sessionBrowser, /createProviderSession/);
  assert.match(sessionBrowser, /const \[newSessionComposer,\s*setNewSessionComposer\]/);
  assert.match(sessionBrowser, /setNewSessionComposer\(\{\s*providerId:\s*providerFilter,\s*workspace:\s*workspacePath,\s*composeId:/s);
  assert.doesNotMatch(sessionBrowser, /const rawSession = await createProviderSession/);
  assert.doesNotMatch(sessionBrowser, /mergeSessionSnapshotsByProvider\(\s*current,\s*providerFilter,\s*nextSessions/s);
  assert.doesNotMatch(sessionBrowser, /setSelectedSessionId\(normalizedSession\.id\)/);
  assert.doesNotMatch(sessionBrowser, /app:\$\{providerFilter\}:/);
  assert.doesNotMatch(sessionBrowser, /writeCachedProviderSessionSnapshot\(providerFilter,\s*nextSessions/);

  assert.match(api, /export async function startProviderSessionMessage\(/);
  assert.match(api, /pending: typeof payload\.pending === "boolean" \? payload\.pending : undefined/);
  assert.match(genericChat, /startProviderSessionMessage/);
  assert.match(sessionBrowser, /mode="new-session"/);
  assert.match(genericChat, /enabled:\s*active && mode !== "new-session" && Boolean\(activeSession\.id\)/);
  assert.match(genericChat, /await onNewSessionStarted\?\.\(sendResult\)/);
  assert.match(genericChat, /if \(sendResult\.pending && sendResult\.accepted !== false\) \{/);
  assert.match(genericChat, /await onNewSessionPending\?\.\(sendResult,\s*trimmedText\)/);
  assert.match(sessionBrowser, /pendingMessage\?: string;/);
  assert.match(sessionBrowser, /pendingSince\?: number;/);
  assert.match(sessionBrowser, /function activityMatchesPendingNewSession/);
  assert.match(sessionBrowser, /activityMatchesPendingNewSession\(item,\s*newSessionComposer\)/);
  assert.match(sessionBrowser, /setSelectedSessionId\(activity\.sessionId\)/);
  assert.match(sessionBrowser, /onNewSessionPending=\{handleNewSessionPending\}/);
});
