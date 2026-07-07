import type { ProviderMetadata } from "../types";

export interface SetupCliTool {
  name: string;
  label?: string;
  bin: string;
  install?: ProviderMetadata["install"] | null;
}

export function buildSetupCliToolsFromProviderMetadata(
  providers: ProviderMetadata[]
): SetupCliTool[];
