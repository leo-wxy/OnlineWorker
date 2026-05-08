export function startSessionStreamLifecycle({
  enabled,
  startCommand,
  stopCommand,
  startArgs,
  createChannel,
  onEvent,
  invokeImpl,
  onError = (message, error) => {
    console.error(message, error);
  },
}) {
  if (!enabled || !startArgs) {
    return undefined;
  }

  const channel = createChannel();
  channel.onmessage = (event) => {
    onEvent(event);
  };

  invokeImpl(startCommand, {
    ...startArgs,
    channel,
  }).catch((error) => {
    onError(`${startCommand} failed`, error);
  });

  return () => {
    invokeImpl(stopCommand).catch((error) => {
      onError(`${stopCommand} failed`, error);
    });
  };
}
