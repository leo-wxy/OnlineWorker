export interface QuotaWindow {
  remainingPercent?: number;
  windowSeconds?: number;
  resetAt?: string | null;
}

export interface QuotaSnapshot {
  status?: "ok" | "error" | "unsupported";
  planType?: string;
  primary?: QuotaWindow | null;
  secondary?: QuotaWindow | null;
  errorCode?: string;
}

export interface AccountSummary {
  id: string;
  stableIdentityDisplay: string;
  authMode: string;
  source: string;
  isCurrent: boolean;
  quota?: QuotaSnapshot;
}

const STORAGE_KEY = "onlineworker.codex.account-summary.v1";

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function finiteNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function quotaWindow(value: unknown): QuotaWindow | null | undefined {
  if (value === null) return null;
  const candidate = record(value);
  if (!candidate) return undefined;
  return {
    remainingPercent: finiteNumber(candidate.remainingPercent),
    windowSeconds: finiteNumber(candidate.windowSeconds),
    resetAt: candidate.resetAt === null || typeof candidate.resetAt === "string" ? candidate.resetAt : undefined,
  };
}

function quotaSnapshot(value: unknown): QuotaSnapshot | undefined {
  const candidate = record(value);
  if (!candidate) return undefined;
  const status = ["ok", "error", "unsupported"].includes(String(candidate.status))
    ? candidate.status as QuotaSnapshot["status"]
    : undefined;
  return {
    status,
    planType: typeof candidate.planType === "string" ? candidate.planType : undefined,
    primary: quotaWindow(candidate.primary),
    secondary: quotaWindow(candidate.secondary),
    errorCode: typeof candidate.errorCode === "string" ? candidate.errorCode : undefined,
  };
}

export function parseAccountSummaries(value: unknown): AccountSummary[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const candidate = record(item);
    if (
      !candidate
      || typeof candidate.id !== "string"
      || typeof candidate.stableIdentityDisplay !== "string"
      || typeof candidate.authMode !== "string"
      || typeof candidate.source !== "string"
    ) return [];
    return [{
      id: candidate.id,
      stableIdentityDisplay: candidate.stableIdentityDisplay,
      authMode: candidate.authMode,
      source: candidate.source,
      isCurrent: candidate.isCurrent === true,
      quota: quotaSnapshot(candidate.quota),
    }];
  });
}

export function loadAccountSummaries(): AccountSummary[] {
  if (typeof window === "undefined") return [];
  try {
    return parseAccountSummaries(JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]"));
  } catch {
    return [];
  }
}

export function saveAccountSummaries(value: unknown): void {
  if (typeof window === "undefined") return;
  try {
    const accounts = parseAccountSummaries(value);
    if (accounts.length) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(accounts));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage may be unavailable; the backend refresh remains authoritative.
  }
}
