import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("app shell wires a collapsible narrow sidebar state", () => {
  const app = readFileSync(join(root, "src", "App.tsx"), "utf8");

  assert.match(app, /const \[sidebarCollapsed,\s*setSidebarCollapsed\] = useState\(false\);/);
  assert.match(app, /sidebarCollapsed \? "w-\[84px\]" : "w-\[248px\]"/);
  assert.match(app, /setSidebarCollapsed\(\(current\) => !current\)/);
  assert.match(app, /title=\{sidebarCollapsed \? t\.app\.sidebar\.expand : t\.app\.sidebar\.collapse\}/);
  assert.match(app, /ow-brand-card[\s\S]*ow-sidebar-toggle/);
  assert.match(app, /ow-brand-card mb-5 flex min-h-16 items-center/);
  assert.match(app, /ow-sidebar-toggle flex w-full items-center/);
  assert.match(app, /!sidebarCollapsed && <span>\{t\.app\.sidebar\.collapse\}<\/span>/);
  assert.match(app, /!sidebarCollapsed && t\.app\.tabs\[key\]/);
});

test("app shell removes the visual drag strip while keeping drag regions", () => {
  const app = readFileSync(join(root, "src", "App.tsx"), "utf8");
  const css = readFileSync(join(root, "src", "index.css"), "utf8");

  assert.equal(app.includes("ow-drag-strip"), false);
  assert.match(app, /data-tauri-drag-region/);
  assert.match(app, /startDragging/);
  assert.equal(css.includes(".ow-drag-strip"), false);
});

test("sidebar collapse labels exist in both locales", () => {
  for (const locale of ["en", "zh"]) {
    const source = readFileSync(join(root, "src", "i18n", "locales", `${locale}.ts`), "utf8");
    assert.match(source, /sidebar:\s*\{/);
    assert.match(source, /collapse:\s*"/);
    assert.match(source, /expand:\s*"/);
  }
});
