import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const h = React.createElement;

function joinClassNames(...parts) {
  return parts.filter(Boolean).join(" ");
}

function createHeading(tag, className) {
  return function Heading({ children }) {
    return h(tag, { className }, children);
  };
}

function Paragraph({ children }) {
  return h(
    "p",
    {
      className:
        "ow-session-md-paragraph my-2.5 leading-[1.72] text-slate-800 whitespace-pre-wrap break-words first:mt-0 last:mb-0",
    },
    children,
  );
}

function List({ ordered, children }) {
  const className = joinClassNames(
    "ow-session-md-list my-3 space-y-1.5 pl-5 leading-[1.68] text-slate-800",
    ordered ? "list-decimal" : "list-disc",
  );
  return h(ordered ? "ol" : "ul", { className }, children);
}

function ListItem({ children }) {
  return h("li", { className: "ow-session-md-list-item pl-1 marker:text-slate-400" }, children);
}

function Blockquote({ children }) {
  return h(
    "blockquote",
    {
      className:
        "ow-session-md-blockquote my-4 rounded-r-2xl border-l-[3px] border-sky-300 bg-sky-50/75 px-4 py-3 text-slate-700",
    },
    children,
  );
}

function Link({ href, children }) {
  return h(
    "a",
    {
      href,
      className:
        "ow-session-md-link font-semibold text-blue-700 underline decoration-blue-200 decoration-2 underline-offset-4 transition-colors hover:text-blue-800 hover:decoration-blue-400",
      target: "_blank",
      rel: "noreferrer noopener",
    },
    children,
  );
}

function codeChildrenToText(children) {
  return React.Children.toArray(children).join("");
}

function isBlockCode(className, children) {
  const text = codeChildrenToText(children);
  return Boolean(className?.includes("language-") || text.includes("\n"));
}

function getCodeLanguage(className) {
  const match = String(className ?? "").match(/language-([^\s]+)/);
  return match?.[1] ?? "text";
}

function CopyButton({ getText }) {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(getText());
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  return h(
    "button",
    {
      type: "button",
      className:
        "ow-session-md-copy-button rounded-lg border border-white/10 bg-white/7 px-2 py-1 text-[11px] font-semibold text-slate-300 transition-colors hover:bg-white/12 hover:text-white",
      "aria-label": "Copy code block",
      onClick: handleCopy,
    },
    copied ? "Copied" : "Copy",
  );
}

function CodeBlock({ className, children }) {
  const language = getCodeLanguage(className);
  const codeText = codeChildrenToText(children).replace(/\n$/, "");

  return h(
    "div",
    {
      className:
        "ow-session-md-code-block my-4 overflow-hidden rounded-xl border border-slate-800 bg-slate-950 text-[13px] leading-relaxed text-slate-100 shadow-inner",
    },
    h(
      "div",
      {
        className:
          "ow-session-md-code-toolbar flex items-center justify-between gap-3 border-b border-white/8 bg-white/[0.03] px-3 py-2",
      },
      h(
        "span",
        {
          className:
            "ow-session-md-code-lang rounded-md bg-white/7 px-2 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400",
        },
        language,
      ),
      h(CopyButton, { getText: () => codeText }),
    ),
    h(
      "pre",
      {
        className:
          "ow-session-md-code-scroll max-h-[420px] overflow-auto px-4 py-3",
      },
      h(
        "code",
        {
          className: joinClassNames("font-mono leading-relaxed text-slate-100", className),
        },
        children,
      ),
    ),
  );
}

function Code({ className, children }) {
  if (!isBlockCode(className, children)) {
    return h(
      "code",
      {
        className: joinClassNames(
          "ow-session-md-inline-code break-words rounded-md border border-slate-200 bg-slate-100 px-1.5 py-0.5 font-mono text-[0.9em] font-semibold text-slate-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.72)]",
          className,
        ),
      },
      children,
    );
  }

  return h(CodeBlock, { className }, children);
}

function Table({ children }) {
  return h(
    "div",
    {
      className:
        "ow-session-md-table-wrap my-4 overflow-x-auto rounded-2xl border border-slate-200 shadow-[inset_-16px_0_18px_-20px_rgba(15,23,42,0.45)]",
    },
    h(
      "table",
      {
        className:
          "ow-session-md-table min-w-full border-collapse bg-white text-left text-[13px] leading-normal text-slate-700",
      },
      children,
    ),
  );
}

function TableHead({ children }) {
  return h("thead", { className: "ow-session-md-table-head bg-slate-50 text-slate-600" }, children);
}

function TableHeader({ children }) {
  return h(
    "th",
    {
      className:
        "ow-session-md-table-header border-b border-slate-200 px-3 py-2 font-bold first:rounded-tl-2xl last:rounded-tr-2xl",
    },
    children,
  );
}

function TableCell({ children }) {
  return h("td", { className: "ow-session-md-table-cell border-t border-slate-100 px-3 py-2 align-top" }, children);
}

export const sessionMarkdownComponents = {
  h1: createHeading(
    "h1",
    "ow-session-md-heading mt-1 mb-3 text-[22px] font-bold leading-tight tracking-[-0.035em] text-slate-950",
  ),
  h2: createHeading(
    "h2",
    "ow-session-md-heading mt-1 mb-3 text-[19px] font-bold leading-tight tracking-[-0.03em] text-slate-950",
  ),
  h3: createHeading(
    "h3",
    "ow-session-md-heading mt-4 mb-2 text-[15px] font-bold leading-snug tracking-[-0.015em] text-slate-900",
  ),
  p: Paragraph,
  ul({ children }) {
    return List({ ordered: false, children });
  },
  ol({ children }) {
    return List({ ordered: true, children });
  },
  li: ListItem,
  blockquote: Blockquote,
  a: Link,
  pre({ children }) {
    return h(React.Fragment, null, children);
  },
  code: Code,
  table: Table,
  thead: TableHead,
  th: TableHeader,
  td: TableCell,
};

export function SessionMarkdownContent({ content }) {
  return h(
    ReactMarkdown,
    {
      remarkPlugins: [remarkGfm],
      components: sessionMarkdownComponents,
    },
    content ?? "",
  );
}

export function renderSessionMarkdownToStaticMarkup(content) {
  return renderToStaticMarkup(h(SessionMarkdownContent, { content }));
}
