import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("provider session event stream hook uses dedicated owner-bridge commands", () => {
  const hook = readFileSync(
    join(root, "src", "hooks", "useProviderSessionEventStream.ts"),
    "utf8",
  );

  assert.match(hook, /startCommand:\s*"start_provider_session_event_stream"/);
  assert.match(hook, /stopCommand:\s*"stop_provider_session_event_stream"/);
  assert.match(
    hook,
    /providerId,\s*sessionId,\s*workspaceDir:\s*workspaceDir \?\? null/s,
  );
});

test("provider session event stream Tauri commands use owner-bridge event streaming only", () => {
  const commands = readFileSync(
    join(root, "src-tauri", "src", "commands", "provider_sessions.rs"),
    "utf8",
  );

  assert.match(commands, /pub async fn start_provider_session_event_stream\(/);
  assert.match(commands, /pub async fn stop_provider_session_event_stream\(\)/);
  assert.match(commands, /"type": "session_event_stream"/);
  assert.match(commands, /Channel<ProviderSessionStreamEvent>/);
  assert.doesNotMatch(commands, /pub async fn start_provider_session_stream\(/);
  assert.doesNotMatch(commands, /pub async fn stop_provider_session_stream\(/);
});

test("session browser chats handle stream-ready and stream errors as non-destructive live updates", () => {
  const genericChat = readFileSync(
    join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"),
    "utf8",
  );

  assert.match(genericChat, /if \(event\?\.kind === "stream_ready"\) \{\s*return;\s*\}/s);
  assert.match(genericChat, /if \(event\?\.kind === "error"\)/);
  assert.match(genericChat, /messagesRef\.current\.length === 0/);
  assert.match(genericChat, /setReplyWatchState\(\(current\) => \(current \? "expired" : current\)\)/);
  assert.match(genericChat, /applySessionStreamEvent\(previousMessages, event\)/);
  assert.match(genericChat, /shouldClearReplyWatch\(previousMessages, nextMessages, event\)/);
});
