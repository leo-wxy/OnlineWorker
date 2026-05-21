import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("session composer exposes attachment staging and selected attachment rendering", () => {
  const shared = readFileSync(join(root, "src", "components", "session-browser", "shared.tsx"), "utf8");
  const api = readFileSync(join(root, "src", "components", "session-browser", "api.ts"), "utf8");
  const sessionBrowser = readFileSync(join(root, "src", "pages", "SessionBrowser.tsx"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");

  assert.match(types, /export interface ComposerAttachment \{/);
  assert.match(types, /kind: "image" \| "file";/);
  assert.match(types, /export interface CodexSendResult \{/);

  assert.match(api, /export async function stageComposerAttachments\(/);
  assert.match(api, /invoke<ComposerAttachment\[]>\("stage_session_composer_attachments"/);
  assert.match(api, /export async function sendCodexMessage\(/);
  assert.match(api, /Promise<CodexSendResult>/);

  assert.match(shared, /attachments,\s*onAttachmentsChange,\s*onPickFiles,\s*supportsAttachments = true,\s*attachmentButtonLabel,\s*imageButtonLabel,/);
  assert.match(shared, /supportsAttachments\?: boolean;/);
  assert.match(shared, /attachments\.length > 0/);
  assert.match(shared, /void onPickFiles\("file", files\)/);
  assert.match(shared, /void onPickFiles\("image", files\)/);
  assert.match(shared, /onAttachmentsChange\(attachments\.filter/);
  assert.match(shared, /onAttachmentsChange\(\[\]\);\s*try\s*{\s*await onSend\(text, attachments\);/s);
  assert.match(shared, /onAttachmentsChange\(attachments\);\s*setDraft\(\(current\) => current \|\| text\);/);
  assert.match(shared, /\{supportsAttachments \? \(/);
  assert.match(sessionBrowser, /const sendResult = await sendCodexMessage/);
  assert.match(sessionBrowser, /if \(sendResult\.threadId && sendResult\.threadId !== threadId\)/);
  assert.match(sessionBrowser, /resolveCodexSessionByThreadId\(sendResult\.threadId\)/);
});
