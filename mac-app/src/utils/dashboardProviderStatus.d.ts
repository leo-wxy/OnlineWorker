export function providerShowsPort(provider: { port?: number | null } | null | undefined): boolean;
export function providerStatusValue<T>(
  provider: { port?: number | null } | null | undefined,
  fallback: T,
): number | T;
