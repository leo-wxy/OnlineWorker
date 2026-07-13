import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SessionMarkdownContent } from "./sessionMarkdown.js";

export function renderSessionMarkdownToStaticMarkup(content) {
  return renderToStaticMarkup(
    React.createElement(SessionMarkdownContent, { content }),
  );
}
