import { emit, listen, type UnlistenFn } from "@tauri-apps/api/event";
import { getCurrentWindow, type Theme } from "@tauri-apps/api/window";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "onlineworker.theme";
export const THEME_EVENT = "app:theme-changed";

const DARK_MODE_QUERY = "(prefers-color-scheme: dark)";
let activePreference: ThemePreference = "system";
let activeCleanup: (() => void) | null = null;

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

function normalizeThemePreference(value: unknown): ThemePreference {
  return isThemePreference(value) ? value : "system";
}

export function readThemePreference(): ThemePreference {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return normalizeThemePreference(value);
  } catch {
    return "system";
  }
}

function getSystemMedia(): MediaQueryList | null {
  try {
    return window.matchMedia?.(DARK_MODE_QUERY) ?? null;
  } catch {
    return null;
  }
}

export function resolveTheme(
  preference: ThemePreference,
  systemTheme: ResolvedTheme = getSystemMedia()?.matches ? "dark" : "light",
): ResolvedTheme {
  return preference === "system" ? systemTheme : preference;
}

function applyResolvedTheme(theme: ResolvedTheme) {
  document.documentElement.dataset.owTheme = theme;
  document.documentElement.style.colorScheme = theme;
}

export function applyThemePreference(
  preference: ThemePreference,
  systemTheme?: ResolvedTheme,
) {
  applyResolvedTheme(resolveTheme(preference, systemTheme));
}

function syncNativeTheme(preference: ThemePreference) {
  try {
    void getCurrentWindow()
      .setTheme(preference === "system" ? null : preference)
      .catch(() => undefined);
  } catch {
    // Browser previews do not expose the Tauri window runtime.
  }
}

export function setThemePreference(preference: ThemePreference): void;
export function setThemePreference(value: unknown) {
  const preference = normalizeThemePreference(value);
  activePreference = preference;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // The active document can still update when storage is unavailable.
  }

  applyThemePreference(preference);
  syncNativeTheme(preference);
  void emit(THEME_EVENT, preference).catch(() => undefined);
}

function registerAsyncCleanup(
  pending: Promise<UnlistenFn>,
  cleanups: UnlistenFn[],
  isDisposed: () => boolean,
) {
  void pending
    .then((unlisten) => {
      if (isDisposed()) {
        runCleanup(unlisten);
      } else {
        cleanups.push(unlisten);
      }
    })
    .catch(() => undefined);
}

function runCleanup(unlisten: UnlistenFn) {
  try {
    void Promise.resolve(unlisten()).catch(() => undefined);
  } catch {
    // Cleanup must not surface during WebView teardown.
  }
}

export function initializeTheme() {
  if (activeCleanup) {
    return activeCleanup;
  }

  activePreference = readThemePreference();
  applyThemePreference(activePreference);
  syncNativeTheme(activePreference);

  const cleanups: UnlistenFn[] = [];
  let disposed = false;
  const media = getSystemMedia();
  if (media) {
    const onMediaChange = (event: MediaQueryListEvent) => {
      if (activePreference !== "system") {
        return;
      }
      applyResolvedTheme(event.matches ? "dark" : "light");
    };
    media.addEventListener("change", onMediaChange);
    cleanups.push(() => media.removeEventListener("change", onMediaChange));
  }

  const onStorage = (event: StorageEvent) => {
    if (event.key !== null && event.key !== THEME_STORAGE_KEY) {
      return;
    }
    activePreference = normalizeThemePreference(event.newValue);
    applyThemePreference(activePreference);
    syncNativeTheme(activePreference);
  };
  window.addEventListener("storage", onStorage);
  cleanups.push(() => window.removeEventListener("storage", onStorage));

  try {
    registerAsyncCleanup(
      getCurrentWindow().onThemeChanged((event) => {
        if (activePreference !== "system") {
          return;
        }
        const theme = event.payload as Theme;
        if (theme === "light" || theme === "dark") {
          applyResolvedTheme(theme);
        }
      }),
      cleanups,
      () => disposed,
    );
  } catch {
    // matchMedia remains the System fallback outside Tauri.
  }

  try {
    registerAsyncCleanup(
      listen<ThemePreference>(THEME_EVENT, (event) => {
        if (!isThemePreference(event.payload)) {
          return;
        }
        activePreference = event.payload;
        applyThemePreference(activePreference);
        syncNativeTheme(activePreference);
      }),
      cleanups,
      () => disposed,
    );
  } catch {
    // The storage listener remains available in browser previews.
  }

  const cleanup = () => {
    if (activeCleanup !== cleanup) {
      return;
    }
    disposed = true;
    for (const unlisten of cleanups.splice(0)) {
      runCleanup(unlisten);
    }
    activeCleanup = null;
  };
  activeCleanup = cleanup;
  return cleanup;
}
