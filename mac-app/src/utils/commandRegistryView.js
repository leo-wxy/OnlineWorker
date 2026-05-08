export const BOT_BACKEND_VIEW = "bot";

export function visibleCommandProviders(providers) {
  return (providers ?? []).filter(
    (provider) => provider?.visible === true && provider?.managed === true && provider?.id
  );
}

export function buildCommandBackendViews(providers) {
  const views = [BOT_BACKEND_VIEW];
  for (const provider of visibleCommandProviders(providers)) {
    if (provider.id !== BOT_BACKEND_VIEW && !views.includes(provider.id)) {
      views.push(provider.id);
    }
  }
  return views;
}

export function matchesCommandBackendView(command, backendView) {
  if (backendView === BOT_BACKEND_VIEW) {
    return command.source === "bot";
  }
  return command.backend === backendView || command.backend === "shared";
}

export function countCommandsForBackendView(commands, backendView, extraPredicate = null) {
  return commands
    .filter((command) => matchesCommandBackendView(command, backendView))
    .filter((command) => (extraPredicate ? extraPredicate(command) : true))
    .length;
}
