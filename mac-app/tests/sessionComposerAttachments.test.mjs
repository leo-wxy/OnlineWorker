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
  const attachmentHook = readFileSync(join(root, "src", "components", "session-browser", "composerAttachments.ts"), "utf8");
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");

  assert.match(types, /export interface ComposerAttachment \{/);
  assert.match(types, /kind: "image" \| "file";/);
  assert.match(types, /export interface ProviderSessionSendResult \{/);

  assert.match(api, /export async function stageComposerAttachments\(/);
  assert.match(api, /invoke<ComposerAttachment\[]>\("stage_session_composer_attachments"/);
  assert.match(api, /export async function sendProviderSessionMessage\(/);
  assert.match(api, /Promise<ProviderSessionSendResult>/);

  assert.match(shared, /attachments,\s*onAttachmentsChange,\s*onPickFiles,\s*supportsAttachments = true,\s*attachmentButtonLabel,\s*imageButtonLabel,/);
  assert.match(shared, /supportsAttachments\?: boolean;/);
  assert.match(shared, /attachments\.length > 0/);
  assert.match(shared, /void onPickFiles\("file", files\)/);
  assert.match(shared, /void onPickFiles\("image", files\)/);
  assert.match(shared, /onAttachmentsChange\(attachments\.filter/);
  assert.match(shared, /onAttachmentsChange\(\[\]\);\s*try\s*{\s*await onSend\(text, attachments\);/s);
  assert.match(shared, /onAttachmentsChange\(attachments\);\s*setDraft\(\(current\) => current \|\| text\);/);
  assert.match(shared, /\{supportsAttachments \? \(/);
  assert.match(attachmentHook, /export function useStagedAttachments/);
  assert.match(attachmentHook, /setError\(unsupportedMessage\)/);
  assert.match(attachmentHook, /const staged = await stageBrowserFiles\(Array\.from\(files\)\)/);
  assert.match(attachmentHook, /setAttachments\(\(current\) => \[\.\.\.current, \.\.\.staged\]\)/);
  assert.match(attachmentHook, /setStagingAttachments\(false\)/);
  assert.match(genericChat, /onPickFiles=\{handlePickFiles\}/);
  assert.match(genericChat, /const sendResult = await sendProviderSessionMessage/);
  assert.match(genericChat, /const remappedSessionId = sendResult\.threadId\?\.trim\(\)/);
  assert.match(genericChat, /await onSessionRemapped\?\.\(activeSession, sendResult\)/);
});
