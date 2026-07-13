import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const main = readFileSync(join(root, "src", "main.tsx"), "utf8");
const mainApp = readFileSync(join(root, "src", "MainApp.tsx"), "utf8");
const app = readFileSync(join(root, "src", "App.tsx"), "utf8");
const sessionMarkdownComponent = readFileSync(
  join(root, "src", "components", "session-browser", "SessionMarkdown.tsx"),
  "utf8",
);
const markdown = readFileSync(join(root, "src", "utils", "sessionMarkdown.js"), "utf8");
const staticMarkdown = readFileSync(
  join(root, "src", "utils", "sessionMarkdownStatic.js"),
  "utf8",
);

test("window entry keeps the menubar direct and lazy-loads the main app", () => {
  assert.match(
    main,
    /import \{ MenubarPopover \} from "\.\/components\/menubar-popover\/MenubarPopover"/,
  );
  assert.match(main, /const MainApp = lazy\(\(\) => import\("\.\/MainApp"\)\)/);
  assert.match(mainApp, /import App from "\.\/App"/);
  assert.match(mainApp, /import \{ I18nProvider \} from "\.\/i18n"/);
  assert.doesNotMatch(app, /MenubarPopover/);
  assert.doesNotMatch(app, /isMenubarPopover/);
});

test("main app lazy-loads heavy pages", () => {
  assert.match(app, /import \{ lazy, Suspense,/);
  assert.doesNotMatch(app, /from "\.\/components";/);
  assert.doesNotMatch(app, /from "\.\/pages";/);
  assert.match(app, /lazy\(\(\) =>\s*import\("\.\/pages\/TaskBoard"\)/);
  assert.match(app, /lazy\(\(\) =>\s*import\("\.\/pages\/SessionBrowser"\)/);
  assert.match(app, /lazy\(\(\) =>\s*import\("\.\/components\/ConfigEditor"\)/);
  assert.match(app, /sessionsMounted && \(/);
  assert.match(app, /<Suspense fallback=\{<PageLoadingState \/>}/);
});

test("session markdown lazy-loads the production renderer", () => {
  assert.match(
    sessionMarkdownComponent,
    /lazy\(\(\) =>\s*import\("\.\.\/\.\.\/utils\/sessionMarkdown\.js"\)/,
  );
  assert.doesNotMatch(markdown, /react-dom\/server/);
  assert.doesNotMatch(markdown, /renderToStaticMarkup/);
  assert.match(staticMarkdown, /react-dom\/server/);
  assert.match(staticMarkdown, /renderToStaticMarkup/);
});
