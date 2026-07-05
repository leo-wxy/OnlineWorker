import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("provider session send flow only merges snapshots after a remap", () => {
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");

  assert.match(
    genericChat,
    /const shouldMergeSnapshot = remappedSessionId && remappedSessionId !== activeSession\.id;/,
  );
  assert.match(
    genericChat,
    /const nextSnapshot = shouldMergeSnapshot\s*\? mergeSessionTurns\(previousMessages, snapshot\)\s*:\s*snapshot;/s,
  );
  assert.doesNotMatch(genericChat, /const mergedSnapshot = mergeSessionTurns\(previousMessages, snapshot\)/);
});

test("provider session view loads codex through generic provider session reads", () => {
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");

  assert.match(genericChat, /const turns = await fetchProviderSession\(activeSession\.type, activeSession\.id, activeSession\.workspace\)/);
  assert.match(genericChat, /const sessionOverlayRaw = \{\s*lastUserMessage: pendingUserMessage,\s*lastEventKind: pendingEventKind,\s*\};/s);
  assert.match(genericChat, /const overlayVisibleUserTurns = useCallback/);
  assert.match(genericChat, /overlayPendingUserTurn\(\s*overlayLocalUserTurns\(turns, localUserTurnsRef\.current\),\s*raw,\s*\)/s);
  assert.match(genericChat, /enabled: active && mode !== "new-session" && Boolean\(activeSession\.id\)/);
  assert.match(genericChat, /usesExtendedReplyPolling/);
  assert.doesNotMatch(genericChat, /fetchCodexThreadState/);
});

test("provider session view keeps snapshot refresh active after the live stream is ready", () => {
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");

  assert.match(genericChat, /startActiveSessionRefresh\(\{/);
  assert.match(genericChat, /intervalMs:\s*3000/);
  assert.match(genericChat, /const liveStreamReadyRef = useRef\(false\)/);
  assert.match(genericChat, /if \(event\?\.kind === "stream_ready"\) \{\s*liveStreamReadyRef\.current = true;\s*return;\s*\}/s);
  assert.match(genericChat, /shouldSkip:\s*\(\) => liveRefreshBlockedRef\.current/);
  assert.doesNotMatch(genericChat, /shouldSkip:\s*\(\) => liveRefreshBlockedRef\.current \|\| liveStreamReadyRef\.current/);
  assert.match(genericChat, /const \[loading, setLoading\] = useState\(true\)/);
  assert.match(
    genericChat,
    /liveRefreshBlockedRef\.current\s*=\s*loading \|\| sending;/,
  );
  assert.doesNotMatch(
    genericChat,
    /liveRefreshBlockedRef\.current\s*=\s*loading \|\| sending \|\| \(replyWatchState !== null && replyWatchState !== "expired"\)/,
  );
  assert.doesNotMatch(
    genericChat,
    /liveRefreshBlockedRef\.current\s*=\s*loading \|\| sending \|\| replyWatchState === "foreground"/,
  );
  assert.match(
    genericChat,
    /Only reset reply polling when the visible session identity changes\./,
  );
  assert.match(
    genericChat,
    /\}, \[active, activeSession\.id, activeSession\.type, activeSession\.workspace, mode\]\);/,
  );
  assert.match(
    genericChat,
    /return overlayVisibleUserTurns\(await fetchProviderSession\(\s*activeSession\.type,\s*activeSession\.id,\s*activeSession\.workspace,\s*\)\);/s,
  );
  assert.doesNotMatch(genericChat, /return mergeSessionTurns\(messagesRef\.current, turns\)/);
  assert.doesNotMatch(genericChat, /messagesRef\.current = nextSnapshot;/);
  assert.doesNotMatch(genericChat, /setMessages\(\[\]\)/);
  assert.match(genericChat, /const overlayed = nextTurns !== turns;/);
  assert.match(
    genericChat,
    /setReplyWatchState\(\(current\) => overlayed \? \(current \?\? "background"\) : \(current === "expired" \? null : current\)\);/,
  );
});

test("session browser keeps existing messages visible during reloads", () => {
  const shared = readFileSync(join(root, "src", "components", "session-browser", "shared.tsx"), "utf8");

  assert.match(shared, /const showLoadingPanel = loading && messages\.length === 0;/);
  assert.match(shared, /const showErrorPanel = Boolean\(error\) && messages\.length === 0;/);
  assert.match(shared, /\{error \? \(\s*<p className="px-3 text-center text-xs text-amber-600">\{error\}<\/p>\s*\) : null\}/s);
});

test("session browser only uses smooth scroll for user-authored appends", () => {
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");

  assert.match(genericChat, /const pendingScrollBehaviorRef = useRef<ScrollBehavior>\("auto"\);/);
  assert.match(genericChat, /const applyMessages = useCallback\(\s*\(\s*nextMessages: SessionTurn\[\],\s*scrollBehavior: ScrollBehavior = "auto"/s);
  assert.match(genericChat, /endRef\.current\?\.scrollIntoView\(\{ behavior \}\);/);
  assert.match(
    genericChat,
    /const overlaySnapshot = overlayVisibleUserTurns\(\s*snapshot,\s*\{\s*lastUserMessage: trimmedText,\s*lastEventKind: "message.user.accepted",\s*\}\s*\);/s,
  );
  assert.match(genericChat, /applyMessages\(optimisticMessages,\s*"smooth"\);/);
  assert.doesNotMatch(genericChat, /scrollIntoView\(\{ behavior: "smooth" \}\)/);
});
