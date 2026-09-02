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

  let disposed = false;
  let streamId;

  const stopStream = (id) => {
    invokeImpl(stopCommand, { streamId: id }).catch((error) => {
      onError(`${stopCommand} failed`, error);
    });
  };

  invokeImpl(startCommand, {
    ...startArgs,
    channel,
  })
    .then((startedStreamId) => {
      streamId = startedStreamId;
      if (disposed) {
        stopStream(startedStreamId);
      }
    })
    .catch((error) => {
      onError(`${startCommand} failed`, error);
    });

  return () => {
    disposed = true;
    if (streamId !== undefined) {
      stopStream(streamId);
    }
  };
}
