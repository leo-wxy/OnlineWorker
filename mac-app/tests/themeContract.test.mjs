import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const appRoot = join(__dirname, "..");
const repoRoot = join(appRoot, "..");
const css = readFileSync(join(appRoot, "src", "index.css"), "utf8");
const guide = readFileSync(join(repoRoot, "docs", "UI-THEME.md"), "utf8");
const docsIndex = readFileSync(join(repoRoot, "docs", "README.md"), "utf8");
const contributing = readFileSync(join(repoRoot, "CONTRIBUTING.md"), "utf8");

const requiredTokenNames = [
  "--ow-bg",
  "--ow-shell",
  "--ow-sidebar",
  "--ow-panel",
  "--ow-panel-soft",
  "--ow-toolbar",
  "--ow-input",
  "--ow-code",
  "--ow-hover",
  "--ow-selected",
  "--ow-disabled-surface",
  "--ow-line",
  "--ow-line-soft",
  "--ow-text",
  "--ow-muted",
  "--ow-subtle",
  "--ow-disabled",
  "--ow-inverse",
  "--ow-focus",
  "--ow-blue",
  "--ow-blue-soft",
  "--ow-green",
  "--ow-green-soft",
  "--ow-amber",
  "--ow-amber-soft",
  "--ow-red",
  "--ow-red-soft",
  "--ow-purple",
  "--ow-purple-soft",
  "--ow-overlay",
  "--ow-shadow-sm",
  "--ow-shadow-md",
  "--ow-shadow-lg",
  "--ow-scrollbar",
  "--ow-scrollbar-hover",
  "--ow-pattern",
];

function themeBlock(name) {
  const pattern =
    name === "light"
      ? /:root,\s*:root\[data-ow-theme="light"\]\s*\{([\s\S]*?)\n\s*\}/
      : /:root\[data-ow-theme="dark"\]\s*\{([\s\S]*?)\n\s*\}/;
  const match = css.match(pattern);
  assert.ok(match, `missing ${name} token block`);
  return match[1];
}

test("light and dark expose the same documented semantic token contract", () => {
  const light = themeBlock("light");
  const dark = themeBlock("dark");
  const readCssTokens = (block) =>
    new Set([...block.matchAll(/^\s*(--ow-[\w-]+)\s*:/gm)].map((match) => match[1]));
  const lightTokens = readCssTokens(light);
  const darkTokens = readCssTokens(dark);
  const documentedTokens = new Set(
    [...guide.matchAll(/`(--ow-[\w-]+)`/g)].map((match) => match[1]),
  );

  for (const token of requiredTokenNames) {
    assert.ok(lightTokens.has(token), `light is missing ${token}`);
  }
  assert.deepEqual([...lightTokens].sort(), [...darkTokens].sort());
  assert.deepEqual([...lightTokens].sort(), [...documentedTokens].sort());
});

test("theme motion is color-only and respects reduced motion", () => {
  assert.match(
    css,
    /transition-property:\s*color, background-color, border-color, box-shadow, fill, stroke;/,
  );
  assert.match(css, /transition-duration:\s*150ms;/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  const reducedMotion = css.match(
    /@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?transition: none !important;[\s\S]*?)\n\}/,
  );
  assert.ok(reducedMotion, "reduced-motion block must disable theme transitions");
  for (const target of ["body", "#root", "button", "input", "select", "textarea", "ow-"]) {
    assert.ok(reducedMotion[1].includes(target), `reduced motion is missing ${target}`);
  }
  assert.doesNotMatch(css, /transition(?:-property)?:[^;]*(?:all|opacity)/);
});

test("the stable guide is discoverable and bans new hardcoded theme colors", () => {
  assert.match(docsIndex, /\[UI Theme Development Guide\]\(UI-THEME\.md\)/);
  assert.match(contributing, /docs\/UI-THEME\.md/);
  assert.match(guide, /bg-white/);
  assert.match(guide, /text-slate-\*/);
  assert.match(guide, /border-slate-\*/);
  assert.match(guide, /hex/i);
  assert.match(guide, /rgba/i);
  assert.match(guide, /System/);
  assert.match(guide, /menubar/i);
});
