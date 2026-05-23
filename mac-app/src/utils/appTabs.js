export const PRIMARY_APP_TABS = ["dashboard", "sessions", "usage", "commands", "notifications", "setup"];

export const ALL_APP_TABS = [...PRIMARY_APP_TABS, "config"];

export function isSupportedAppTab(value) {
  return ALL_APP_TABS.includes(value);
}
