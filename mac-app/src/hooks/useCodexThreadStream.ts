import type { CodexThreadCursor, CodexThreadStreamEvent } from "../types";
import { useSessionStream } from "./useSessionStream";

interface UseCodexThreadStreamOptions {
  enabled: boolean;
  rolloutPath: string | null;
  cursor: CodexThreadCursor | null;
  onEvent: (event: CodexThreadStreamEvent) => void;
}

export function useCodexThreadStream({
  enabled,
  rolloutPath,
  cursor,
  onEvent,
}: UseCodexThreadStreamOptions): void {
  useSessionStream<CodexThreadStreamEvent>({
    enabled,
    startCommand: "start_codex_thread_stream",
    stopCommand: "stop_codex_thread_stream",
    startArgs: enabled && rolloutPath && cursor
      ? {
        rolloutPath,
        cursor,
      }
      : null,
    deps: [rolloutPath, cursor?.offset],
    onEvent,
  });
}
