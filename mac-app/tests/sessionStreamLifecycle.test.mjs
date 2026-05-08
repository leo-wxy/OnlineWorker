import test from "node:test";
import assert from "node:assert/strict";

import { startSessionStreamLifecycle } from "../src/hooks/sessionStreamLifecycle.js";

test("startSessionStreamLifecycle skips startup when disabled", () => {
  const invocations = [];

  const cleanup = startSessionStreamLifecycle({
    enabled: false,
    startCommand: "start_dummy",
    stopCommand: "stop_dummy",
    startArgs: { sessionId: "s-1" },
    createChannel: () => ({ onmessage: null }),
    onEvent: () => {},
    invokeImpl: async (command, args) => {
      invocations.push({ command, args });
    },
  });

  assert.equal(cleanup, undefined);
  assert.equal(invocations.length, 0);
});

test("startSessionStreamLifecycle starts stream, forwards events, and stops on cleanup", async () => {
  const invocations = [];
  const receivedEvents = [];
  const channel = { onmessage: null };

  const cleanup = startSessionStreamLifecycle({
    enabled: true,
    startCommand: "start_customprovider_session_stream",
    stopCommand: "stop_customprovider_session_stream",
    startArgs: { sessionId: "session-1" },
    createChannel: () => channel,
    onEvent: (event) => {
      receivedEvents.push(event);
    },
    invokeImpl: async (command, args) => {
      invocations.push({ command, args });
    },
  });

  assert.equal(typeof cleanup, "function");
  assert.equal(invocations.length, 1);
  assert.equal(invocations[0].command, "start_customprovider_session_stream");
  assert.equal(invocations[0].args.sessionId, "session-1");
  assert.equal(invocations[0].args.channel, channel);

  channel.onmessage?.({ kind: "assistant_completed", turn: { role: "assistant", content: "ok" } });
  assert.equal(receivedEvents.length, 1);
  assert.equal(receivedEvents[0].kind, "assistant_completed");

  cleanup?.();
  await Promise.resolve();

  assert.equal(invocations.length, 2);
  assert.equal(invocations[1].command, "stop_customprovider_session_stream");
});
