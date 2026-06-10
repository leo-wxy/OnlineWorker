import type { SessionStreamEvent } from "../types";
import { useSessionStream } from "./useSessionStream";

interface UseProviderSessionEventStreamOptions {
  enabled: boolean;
  providerId: string;
  sessionId: string;
  workspaceDir?: string | null;
  onEvent: (event: SessionStreamEvent) => void;
}

export function useProviderSessionEventStream({
  enabled,
  providerId,
  sessionId,
  workspaceDir,
  onEvent,
}: UseProviderSessionEventStreamOptions): void {
  useSessionStream<SessionStreamEvent>({
    enabled,
    startCommand: "start_provider_session_event_stream",
    stopCommand: "stop_provider_session_event_stream",
    startArgs: enabled
      ? {
          providerId,
          sessionId,
          workspaceDir: workspaceDir ?? null,
        }
      : null,
    deps: [providerId, sessionId, workspaceDir ?? ""],
    onEvent,
  });
}
