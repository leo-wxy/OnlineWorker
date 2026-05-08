export function getSessionStreamKind(event, { preferSemantic = false } = {}) {
  const legacyKind = typeof event?.kind === "string" ? event.kind.trim() : "";
  const semanticKind = typeof event?.semanticKind === "string" ? event.semanticKind.trim() : "";

  if (preferSemantic && semanticKind) {
    return semanticKind;
  }
  if (legacyKind) {
    return legacyKind;
  }
  return semanticKind;
}

