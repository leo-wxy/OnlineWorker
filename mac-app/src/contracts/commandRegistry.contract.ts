import type {
  CommandBackend,
  CommandRegistryEntry,
  CommandRegistryResponse,
  CommandSource,
  CommandStatus,
} from "../types";
import { CommandRegistry } from "../pages";
import { useCommandRegistry } from "../hooks";

function assertType<T>(_value: T): void {}

type HookResult = ReturnType<typeof useCommandRegistry>;

assertType<HookResult>(null as unknown as HookResult);
assertType<CommandRegistryResponse>(null as unknown as CommandRegistryResponse);
assertType<CommandRegistryEntry>(null as unknown as CommandRegistryEntry);
assertType<CommandSource>(null as unknown as CommandSource);
assertType<CommandBackend>(null as unknown as CommandBackend);
assertType<CommandStatus>(null as unknown as CommandStatus);
assertType<typeof CommandRegistry>(CommandRegistry);

export const commandRegistryContract = true;
