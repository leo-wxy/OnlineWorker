export interface CliEntry {
  name: string;
  bin: string;
}

export function parseCliEntriesFromConfigRaw(raw: string): CliEntry[];
