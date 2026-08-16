import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const theme = read("../src/utils/theme.ts");
const html = read("../index.html");
const main = read("../src/main.tsx");
const menubar = read("../src/components/menubar-popover/MenubarPopover.tsx");
const capability = JSON.parse(
  read("../src-tauri/capabilities/default.json"),
);

test("theme runtime keeps one validated system/light/dark preference", () => {
  assert.match(theme, /ThemePreference = "system" \| "light" \| "dark"/);
  assert.match(theme, /ResolvedTheme = "light" \| "dark"/);
  assert.match(theme, /THEME_STORAGE_KEY = "onlineworker\.theme"/);
  assert.match(theme, /isThemePreference/);
  assert.match(theme, /return "system"/);
  assert.match(theme, /localStorage\.getItem\(THEME_STORAGE_KEY\)/);
  assert.match(theme, /localStorage\.setItem\(THEME_STORAGE_KEY, preference\)/);
  assert.match(theme, /normalizeThemePreference\(value\)/);
  assert.match(theme, /catch \{/);
});

test("first-frame bootstrap runs before the module and React root", () => {
  const bootstrapIndex = html.indexOf("onlineworker.theme");
  const moduleIndex = html.indexOf('type="module"');
  const initIndex = main.indexOf("initializeTheme()");
  const rootIndex = main.indexOf("ReactDOM.createRoot");

  assert.ok(bootstrapIndex >= 0);
  assert.ok(moduleIndex > bootstrapIndex);
  assert.match(html, /data-ow-theme|dataset\.owTheme/);
  assert.match(html, /prefers-color-scheme: dark/);
  assert.ok(initIndex >= 0);
  assert.ok(rootIndex > initIndex);
});

test("theme sync separates System changes from explicit preferences", () => {
  assert.match(theme, /DARK_MODE_QUERY = "\(prefers-color-scheme: dark\)"/);
  assert.match(theme, /matchMedia\?\.\(DARK_MODE_QUERY\)/);
  assert.match(theme, /onThemeChanged/);
  assert.match(theme, /activePreference !== "system"/);
  assert.match(theme, /setTheme\(preference === "system" \? null : preference\)/);
  assert.match(theme, /THEME_EVENT = "app:theme-changed"/);
  assert.match(theme, /emit\(THEME_EVENT, preference\)/);
  assert.match(theme, /listen<ThemePreference>\(THEME_EVENT/);
  assert.match(theme, /addEventListener\("storage"/);
  assert.match(theme, /removeEventListener\("storage"/);
  assert.match(theme, /removeEventListener\("change"/);
  assert.match(theme, /Promise\.resolve\(unlisten\(\)\)\.catch/);
  assert.match(theme, /event\.key !== null/);
  assert.match(theme, /if \(activeCleanup\)/);
  assert.match(theme, /return cleanup/);
  assert.equal(menubar.includes("setThemePreference"), false);
});

test("theme setter uses only the minimum existing-window capability", () => {
  assert.deepEqual(capability.windows, ["main", "menubar-popover"]);
  assert.ok(capability.permissions.includes("core:window:allow-set-theme"));
  assert.equal(capability.permissions.includes("core:app:allow-set-app-theme"), false);
});
