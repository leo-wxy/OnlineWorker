export type AppTab = "dashboard" | "sessions" | "commands" | "config" | "setup";

export const PRIMARY_APP_TABS: readonly AppTab[];
export const ALL_APP_TABS: readonly AppTab[];

export function isSupportedAppTab(value: string): value is AppTab;
