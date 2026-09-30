import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import { sessionIdentityKey } from "../src/utils/sessionBrowserState.js";

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function loadFunction(path, name, globals) {
  const file = ts.createSourceFile(path, readFileSync(new URL(path, import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let declaration;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(file) === name) declaration = node.initializer.getText(file);
    ts.forEachChild(node, visit);
  }
  visit(file);
  assert.ok(declaration);
  const source = ts.transpile(`globalThis.result = ${declaration}`, { target: ts.ScriptTarget.ES2022 });
  const context = vm.createContext(globals);
  vm.runInContext(source, context);
  return context.result;
}

test("chat identities include provider, session and workspace", () => {
  const session = { type: "codex", id: "sample-session", workspace: "/tmp/sample-workspace" };
  const key = sessionIdentityKey(session);
  assert.notEqual(key, sessionIdentityKey({ ...session, type: "claude" }));
  assert.notEqual(key, sessionIdentityKey({ ...session, workspace: "/tmp/another-workspace" }));
});

for (const fails of [false, true]) {
  test(`late send ${fails ? "failure" : "success"} cannot update the new chat scope`, async () => {
    const send = deferred();
    const writes = [];
    const scopeGenerationRef = { current: 1 };
    const record = (...args) => writes.push(args);
    const handleSend = loadFunction("../src/components/session-browser/GenericProviderChat.tsx", "handleSend", {
      messagesRef: { current: [] }, limitSessionTurns: (value) => value,
      replyWatchTokenRef: { current: 0 }, scopeGenerationRef,
      countAssistantEntries: () => 0,
      mode: "session", activeSession: { type: "codex", id: "sample-session", workspace: "/tmp/sample-workspace" },
      sendProviderSessionMessage: () => send.promise,
      setSending: record, setError: record, applyMessages: record,
      setReplyWatchState: record, cancelReplyWatch: record, setAttachments: record,
      setActiveSession: record, onSessionRemapped: record,
    });
    const pending = handleSend("sample message", []);
    const before = writes.length;
    scopeGenerationRef.current += 1;
    if (fails) send.reject(new Error("sample send failed"));
    else send.resolve({ accepted: true, threadId: "different-session" });
    await pending;
    assert.equal(writes.length, before);
  });
}

test("archive A finishing after selecting B preserves B", async () => {
  const archive = deferred();
  const a = { type: "codex", id: "session-a", workspace: "/tmp/sample-workspace" };
  let selected = a.id;
  const archiveScopeRef = { current: { providerId: "codex", session: a } };
  const handler = loadFunction("../src/pages/SessionBrowser.tsx", "handleArchiveSession", {
    useCallback: (fn) => fn,
    archivingSessionId: null, selectedSessionId: a.id, archiveScopeRef, sessionIdentityKey,
    setSessionContextMenu() {}, setArchivingSessionId() {}, setArchiveNotice() {},
    setSelectedSessionId: (update) => { selected = update(selected); },
    refreshCurrentProvider: async () => {}, t: { sessions: { archiveSucceeded: "done", archiveFailed: () => "failed" } },
    archiveSessionWithFeedback: async ({ onArchivedSelection }) => {
      await archive.promise;
      onArchivedSelection();
      return { tone: "success", text: "done" };
    },
  });
  const pending = handler(a);
  selected = "session-b";
  archiveScopeRef.current = { providerId: "codex", session: { ...a, id: selected } };
  archive.resolve();
  await pending;
  assert.equal(selected, "session-b");
});

test("attachment staging completion cannot write after scope cleanup", async () => {
  const stage = deferred();
  let cleanup;
  const writes = [];
  const path = "../src/components/session-browser/composerAttachments.ts";
  const source = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const exports = {};
  vm.runInNewContext(source, {
    exports,
    require: (name) => name === "react" ? {
      useCallback: (fn) => fn, useRef: () => ({ current: 0 }),
      useState: () => [false, (value) => writes.push(value)],
      useEffect: (fn) => { cleanup = fn(); },
    } : { stageComposerAttachments: () => stage.promise },
  });
  const hook = exports.useStagedAttachments({ scopeKey: "sample", supportsAttachments: true,
    unsupportedMessage: "unsupported", setError: (value) => writes.push(value),
    setAttachments: (value) => writes.push(value) });
  const pending = hook.handlePickFiles("file", []);
  await Promise.resolve();
  cleanup();
  const before = writes.length;
  stage.resolve([{ id: "sample-attachment" }]);
  await pending;
  assert.equal(writes.length, before);
});
