import { useEffect, useRef } from "react";
import { invoke, Channel } from "@tauri-apps/api/core";
import { startSessionStreamLifecycle } from "./sessionStreamLifecycle.js";

interface UseSessionStreamOptions<TEvent> {
  enabled: boolean;
  startCommand: string;
  stopCommand: string;
  startArgs: Record<string, unknown> | null;
  deps: readonly unknown[];
  onEvent: (event: TEvent) => void;
}

export function useSessionStream<TEvent>({
  enabled,
  startCommand,
  stopCommand,
  startArgs,
  deps,
  onEvent,
}: UseSessionStreamOptions<TEvent>): void {
  const onEventRef = useRef(onEvent);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    return startSessionStreamLifecycle<TEvent>({
      enabled,
      startCommand,
      stopCommand,
      startArgs,
      createChannel: () => new Channel<TEvent>(),
      onEvent: (event) => {
        onEventRef.current(event);
      },
      invokeImpl: (command, args) => invoke(command, args),
    });
  }, [enabled, startCommand, stopCommand, ...deps]);
}
