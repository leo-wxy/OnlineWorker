import type { ProviderMetadata } from "../types";

export interface SetupCliTool {
  name: string;
  label?: string;
  bin: string;
}

export interface CliInstallStep {
  desc: string;
  cmd: string;
}

export interface CliInstallInfo {
  label: string;
  steps: CliInstallStep[];
  docsUrl?: string;
}

export interface CliCheckerTexts {
  installViaNpm: string;
  installViaOfficialInstaller: string;
  installManually: (bin: string) => string;
}

export function buildSetupCliToolsFromProviderMetadata(
  providers: ProviderMetadata[]
): SetupCliTool[];

export function getCliInstallInfo(
  toolName: string,
  bin: string,
  texts: CliCheckerTexts
): CliInstallInfo;
