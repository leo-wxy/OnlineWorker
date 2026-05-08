import * as yaml from "js-yaml";

function upsertEntry(entries, name, bin) {
  const normalizedName = String(name ?? "").trim();
  const normalizedBin = String(bin ?? "").trim();
  if (!normalizedName || !normalizedBin) {
    return;
  }
  if (!entries.has(normalizedName)) {
    entries.set(normalizedName, { name: normalizedName, bin: normalizedBin });
  }
}

function providerVisibleByDefault(name, record) {
  if (typeof record.visible === "boolean") {
    return record.visible;
  }
  return true;
}

export function parseCliEntriesFromConfigRaw(raw) {
  try {
    const doc = yaml.load(raw);
    const entries = new Map();

    if (doc?.providers && typeof doc.providers === "object" && !Array.isArray(doc.providers)) {
      for (const [name, provider] of Object.entries(doc.providers)) {
        const record = provider && typeof provider === "object" ? provider : {};
        if (!providerVisibleByDefault(name, record)) {
          continue;
        }
        upsertEntry(entries, name, record.bin ?? record.codex_bin ?? record.codexBin);
      }
    }

    if (Array.isArray(doc?.tools)) {
      for (const tool of doc.tools) {
        const record = tool && typeof tool === "object" ? tool : {};
        upsertEntry(entries, record.name, record.codex_bin ?? record.codexBin ?? record.bin);
      }
    }

    return Array.from(entries.values());
  } catch {
    return [];
  }
}

export function visibleProviderMetadata(providers) {
  return (providers ?? []).filter((provider) => provider?.visible === true);
}

export function providerCliEntriesFromMetadata(providers) {
  return visibleProviderMetadata(providers)
    .map((provider) => ({
      name: provider.id,
      label: provider.label || provider.id,
      bin: provider.bin || provider.install?.cliNames?.[0] || provider.id,
    }))
    .filter((entry) => entry.name && entry.bin);
}
