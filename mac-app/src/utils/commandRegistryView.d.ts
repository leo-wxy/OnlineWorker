import type { CommandRegistryEntry, ProviderMetadata } from "../types";

export type CommandBackendView = string;

export const BOT_BACKEND_VIEW: "bot";

export function visibleCommandProviders(providers: ProviderMetadata[]): ProviderMetadata[];

export function buildCommandBackendViews(providers: ProviderMetadata[]): CommandBackendView[];

export function matchesCommandBackendView(
  command: Pick<CommandRegistryEntry, "source" | "backend">,
  backendView: CommandBackendView,
): boolean;

export function countCommandsForBackendView(
  commands: Array<Pick<CommandRegistryEntry, "source" | "backend">>,
  backendView: CommandBackendView,
  extraPredicate?: ((command: CommandRegistryEntry) => boolean) | null,
): number;
