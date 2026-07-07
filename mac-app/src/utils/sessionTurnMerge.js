const SESSION_BROWSER_VISIBLE_TURNS = 50;

export function limitSessionTurns(turns) {
  return turns.length <= SESSION_BROWSER_VISIBLE_TURNS
    ? turns
    : turns.slice(-SESSION_BROWSER_VISIBLE_TURNS);
}

function hasAttachmentWrapperMarkers(content) {
  const text = String(content ?? "");
  return /<image\b[^>]*>|<\/image>|\[Attached (?:image|file)\]/i.test(text);
}

function normalizeAttachmentNoise(content) {
  return String(content ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => {
      if (!line) {
        return false;
      }
      if (/^<image\b[^>]*>$/i.test(line)) {
        return false;
      }
      if (/^<\/image>$/i.test(line)) {
        return false;
      }
      if (/^\[Attached (?:image|file)\]/i.test(line)) {
        return false;
      }
      if (/^Path:\s*/i.test(line)) {
        return false;
      }
      return true;
    })
    .join("\n")
    .trim();
}

function isSameLogicalTurn(left, right) {
  if (!left || !right || left.role !== right.role) {
    return false;
  }
  if (left.content === right.content) {
    return true;
  }
  if (!(hasAttachmentWrapperMarkers(left.content) || hasAttachmentWrapperMarkers(right.content))) {
    return false;
  }
  return normalizeAttachmentNoise(left.content) === normalizeAttachmentNoise(right.content);
}

function normalizedString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function pendingUserEventKind(raw) {
  const kind = normalizedString(raw?.lastEventKind ?? raw?.last_event_kind);
  return kind === "message.user.submitted"
    || kind === "message.user.accepted";
}

export function overlayPendingUserTurn(turns, raw) {
  const pendingText = normalizedString(raw?.lastUserMessage ?? raw?.last_user_message);
  if (!pendingText || !pendingUserEventKind(raw)) {
    return turns;
  }
  if (turns.some((turn) => turn?.role === "user" && isSameLogicalTurn(turn, { role: "user", content: pendingText }))) {
    return turns;
  }
  return limitSessionTurns([
    ...turns,
    {
      role: "user",
      content: pendingText,
      displayMode: "plain",
    },
  ]);
}

function completedAssistantCountBefore(turns, index) {
  let count = 0;
  for (let cursor = 0; cursor < index; cursor += 1) {
    const turn = turns[cursor];
    if (turn?.role === "assistant" && turn.pending !== true && normalizedString(turn.content)) {
      count += 1;
    }
  }
  return count;
}

function insertLocalUserTurn(turns, localTurn) {
  const content = normalizedString(localTurn?.content);
  if (!content) {
    return turns;
  }
  const userTurn = {
    role: "user",
    content,
    displayMode: "plain",
  };
  if (turns.some((turn) => turn?.role === "user" && isSameLogicalTurn(turn, userTurn))) {
    return turns;
  }

  const afterAssistantCount = Math.max(0, Number(localTurn?.afterAssistantCount) || 0);
  let insertIndex = turns.length;
  for (let index = 0; index < turns.length; index += 1) {
    const turn = turns[index];
    if (
      turn?.role === "assistant"
      && turn.pending !== true
      && normalizedString(turn.content)
      && completedAssistantCountBefore(turns, index) >= afterAssistantCount
    ) {
      insertIndex = index;
      break;
    }
  }

  return [
    ...turns.slice(0, insertIndex),
    userTurn,
    ...turns.slice(insertIndex),
  ];
}

export function overlayLocalUserTurns(turns, localTurns) {
  if (!Array.isArray(localTurns) || localTurns.length === 0) {
    return turns;
  }
  return limitSessionTurns(localTurns.reduce(insertLocalUserTurn, turns));
}

export function mergeSessionTurns(existing, incoming) {
  if (incoming.length === 0) {
    return existing;
  }

  const incomingHasCompletedAssistant = incoming.some(
    (turn) => turn.role === "assistant" && turn.pending !== true && turn.content.trim().length > 0,
  );
  const merged = incomingHasCompletedAssistant
    ? existing.filter((turn) => !(turn.role === "assistant" && turn.pending === true))
    : [...existing];
  for (const turn of incoming) {
    const last = merged[merged.length - 1];
    if (last?.role === "assistant" && last?.pending && turn.role === "assistant") {
      merged[merged.length - 1] = {
        ...turn,
        pending: Boolean(turn.pending),
      };
      continue;
    }
    if (last && isSameLogicalTurn(last, turn)) {
      merged[merged.length - 1] = {
        ...turn,
        pending: Boolean(turn.pending),
      };
      continue;
    }
    merged.push(turn);
  }

  return limitSessionTurns(merged);
}
