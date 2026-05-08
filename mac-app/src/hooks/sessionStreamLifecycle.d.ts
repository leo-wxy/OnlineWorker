export interface SessionStreamLifecycleOptions<TEvent> {
  enabled: boolean;
  startCommand: string;
  stopCommand: string;
  startArgs: Record<string, unknown> | null;
  createChannel: () => {
    onmessage?: ((event: TEvent) => void) | null;
  };
  onEvent: (event: TEvent) => void;
  invokeImpl: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
  onError?: (message: string, error: unknown) => void;
}

export function startSessionStreamLifecycle<TEvent>(
  options: SessionStreamLifecycleOptions<TEvent>,
): (() => void) | undefined;
