import type { ProviderMetadata } from "../types";

export interface ProviderSettingView {
  id: string;
  label: string;
  enabled: boolean;
  autostart: boolean;
  bin?: string | null;
}

export function primaryProviderSettings(providers: ProviderMetadata[]): ProviderSettingView[];

export function extensionProviderSettings(providers: ProviderMetadata[]): ProviderSettingView[];
