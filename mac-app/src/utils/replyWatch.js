import { hasAdvancedAssistantReply } from "./sessionPolling.js";
import { getSessionStreamKind } from "./sessionStreamKinds.js";

export function shouldClearReplyWatch(previousSnapshot, nextSnapshot, event) {
  const eventKind = getSessionStreamKind(event, { preferSemantic: true });
  if (!eventKind) {
    return false;
  }

  if (eventKind === "turn_aborted" || eventKind === "error") {
    return true;
  }

  return hasAdvancedAssistantReply(previousSnapshot, nextSnapshot);
}
