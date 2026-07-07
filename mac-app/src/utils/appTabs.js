export const PRIMARY_APP_TABS = ["dashboard", "tasks", "sessions", "usage", "ai", "commands", "notifications", "setup"];

const ALL_APP_TABS = [...PRIMARY_APP_TABS, "config"];

export function isSupportedAppTab(value) {
  return ALL_APP_TABS.includes(value);
}
