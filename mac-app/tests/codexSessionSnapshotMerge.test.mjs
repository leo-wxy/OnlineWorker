import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("provider session remap switches the stream identity without a second snapshot read", () => {
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");

  assert.match(genericChat, /if \(remappedSessionId && remappedSessionId !== activeSession\.id\)/);
  assert.match(genericChat, /setActiveSession\(nextSession\)/);
  assert.doesNotMatch(genericChat, /fetchProviderSession|mergeSessionTurns/);
});

test("provider session view loads through the generic message center stream", () => {
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");

  assert.match(genericChat, /enabled: active && mode !== "new-session" && Boolean\(activeSession\.id\)/);
  assert.match(genericChat, /providerId: activeSession\.type/);
  assert.match(genericChat, /sessionId: activeSession\.id/);
  assert.match(genericChat, /workspaceDir: activeSession\.workspace/);
  assert.doesNotMatch(genericChat, /fetchCodexThreadState/);
});

test("provider session view applies recovery snapshots without background polling", () => {
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");

  assert.doesNotMatch(genericChat, /startActiveSessionRefresh|setInterval|fetchProviderSession|usesExtendedReplyPolling/);
  assert.match(genericChat, /if \(event\?\.kind === "stream_ready"\) \{\s*return;\s*\}/s);
  assert.match(genericChat, /const \[loading, setLoading\] = useState\(true\)/);
  assert.match(genericChat, /applySessionStreamEvent\(previousMessages, event\)/);
  assert.match(genericChat, /applyMessages\(nextMessages, "auto"\)/);
  assert.match(genericChat, /setStreamReloadKey\(\(current\) => current \+ 1\)/);
  assert.doesNotMatch(genericChat, /setMessages\(\[\]\)/);
});

test("session browser keeps existing messages visible during reloads", () => {
  const shared = readFileSync(join(root, "src", "components", "session-browser", "shared.tsx"), "utf8");

  assert.match(shared, /const showLoadingPanel = loading && messages\.length === 0;/);
  assert.match(shared, /const showErrorPanel = Boolean\(error\) && messages\.length === 0;/);
  assert.match(shared, /\{error \? \(\s*<p className="px-3 text-center text-xs text-\[var\(--ow-warning-text\)\]">\{error\}<\/p>\s*\) : null\}/s);
});

test("session browser only uses smooth scroll for user-authored appends", () => {
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");

  assert.match(genericChat, /const pendingScrollBehaviorRef = useRef<ScrollBehavior>\("auto"\);/);
  assert.match(genericChat, /const applyMessages = useCallback\(\s*\(\s*nextMessages: SessionTurn\[\],\s*scrollBehavior: ScrollBehavior = "auto"/s);
  assert.match(genericChat, /endRef\.current\?\.scrollIntoView\(\{ behavior \}\);/);
  assert.match(genericChat, /applyMessages\(optimisticMessages,\s*"smooth"\);/);
  assert.doesNotMatch(genericChat, /scrollIntoView\(\{ behavior: "smooth" \}\)/);
});
