import test from "node:test";
import assert from "node:assert/strict";

test("renderSessionMarkdownToStaticMarkup renders list and code block structure", async () => {
  const markdownModule = await import("../src/utils/sessionMarkdown.js").catch(() => null);

  assert.ok(
    markdownModule && typeof markdownModule.renderSessionMarkdownToStaticMarkup === "function",
    "expected session markdown renderer to be available",
  );

  const html = markdownModule.renderSessionMarkdownToStaticMarkup(
    [
      "## 已完成",
      "",
      "- 收口 App 最终态渲染",
      "- 补齐 Telegram fallback",
      "",
      "```ts",
      "const done = true;",
      "```",
    ].join("\n"),
  );

  assert.match(html, /<h2[^>]*>已完成<\/h2>/);
  assert.match(html, /<ul[^>]*>/);
  assert.match(html, /<li[^>]*>收口 App 最终态渲染<\/li>/);
  assert.match(html, /<pre/);
  assert.doesNotMatch(html, /<pre><pre/);
  assert.match(html, /const done = true;/);
});

test("renderSessionMarkdownToStaticMarkup keeps inline code inline", async () => {
  const markdownModule = await import("../src/utils/sessionMarkdown.js").catch(() => null);

  assert.ok(
    markdownModule && typeof markdownModule.renderSessionMarkdownToStaticMarkup === "function",
    "expected session markdown renderer to be available",
  );

  const html = markdownModule.renderSessionMarkdownToStaticMarkup(
    'TG 日志里的 `HTML edit` 不代表 App 使用 `dangerouslySetInnerHTML`。',
  );

  assert.match(html, /<p[^>]*>/);
  assert.match(html, /<code[^>]*>HTML edit<\/code>/);
  assert.match(html, /<code[^>]*>dangerouslySetInnerHTML<\/code>/);
  assert.doesNotMatch(html, /<pre/);
});

test("renderSessionMarkdownToStaticMarkup applies readable session markdown styles", async () => {
  const markdownModule = await import("../src/utils/sessionMarkdown.js").catch(() => null);

  assert.ok(
    markdownModule && typeof markdownModule.renderSessionMarkdownToStaticMarkup === "function",
    "expected session markdown renderer to be available",
  );

  const html = markdownModule.renderSessionMarkdownToStaticMarkup(
    [
      "## 渲染结论",
      "",
      "> App Session Tab 继续使用 Markdown AST。",
      "",
      "- 修复 `inline code`",
      "- 保留代码块",
      "",
      "```ts",
      "const displayMode = \"markdown\";",
      "```",
      "",
      "| 项目 | 结果 |",
      "| --- | --- |",
      "| inline | 小胶囊 |",
    ].join("\n"),
  );

  assert.match(html, /ow-session-md-heading/);
  assert.match(html, /ow-session-md-blockquote/);
  assert.match(html, /ow-session-md-list/);
  assert.match(html, /ow-session-md-inline-code/);
  assert.match(html, /ow-session-md-code-block/);
  assert.match(html, /ow-session-md-table/);
});

test("renderSessionMarkdownToStaticMarkup exposes P0 markdown usability affordances", async () => {
  const markdownModule = await import("../src/utils/sessionMarkdown.js").catch(() => null);

  assert.ok(
    markdownModule && typeof markdownModule.renderSessionMarkdownToStaticMarkup === "function",
    "expected session markdown renderer to be available",
  );

  const html = markdownModule.renderSessionMarkdownToStaticMarkup(
    [
      "Use `reallyLongIdentifier.with.deep.path.and.no.spaces` safely.",
      "",
      "```ts",
      "const displayMode = \"markdown\";",
      "```",
      "",
      "| really long column | result |",
      "| --- | --- |",
      "| value | ok |",
    ].join("\n"),
  );

  assert.match(html, /ow-session-md-copy-button/);
  assert.match(html, /aria-label="Copy code block"/);
  assert.match(html, /<span class="ow-session-md-code-lang[^"]*">ts<\/span>/);
  assert.match(html, /ow-session-md-code-scroll[^"]*max-h-\[420px\]/);
  assert.match(html, /ow-session-md-inline-code[^"]*break-words/);
  assert.match(html, /ow-session-md-table-wrap[^"]*shadow-\[inset_-16px_0_18px_-20px_rgba\(15,23,42,0\.45\)\]/);
});
