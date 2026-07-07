import { hasAdvancedAssistantReply } from "./sessionPolling.js";

export function shouldClearReplyWatch(previousSnapshot, nextSnapshot, event) {
  const eventKind =
    (typeof event?.semanticKind === "string" && event.semanticKind.trim()) ||
    (typeof event?.kind === "string" && event.kind.trim());
  if (!eventKind) {
    return false;
  }

  if (eventKind === "turn_aborted" || eventKind === "error") {
    return true;
  }

  return hasAdvancedAssistantReply(previousSnapshot, nextSnapshot);
}
