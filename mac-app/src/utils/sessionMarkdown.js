import React from "react";
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
        "ow-session-md-paragraph my-2.5 leading-[1.72] text-[var(--ow-text)] whitespace-pre-wrap break-words first:mt-0 last:mb-0",
    },
    children,
  );
}

function List({ ordered, children }) {
  const className = joinClassNames(
    "ow-session-md-list my-3 space-y-1.5 pl-5 leading-[1.68] text-[var(--ow-text)]",
    ordered ? "list-decimal" : "list-disc",
  );
  return h(ordered ? "ol" : "ul", { className }, children);
}

function ListItem({ children }) {
  return h("li", { className: "ow-session-md-list-item pl-1 marker:text-[var(--ow-subtle)]" }, children);
}

function Blockquote({ children }) {
  return h(
    "blockquote",
    {
      className:
        "ow-session-md-blockquote my-4 rounded-r-2xl border-l-[3px] border-[var(--ow-blue)] bg-[var(--ow-blue-soft)] px-4 py-3 text-[var(--ow-text)]",
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
        "ow-session-md-link font-semibold text-[var(--ow-blue)] underline decoration-[var(--ow-blue)] decoration-2 underline-offset-4 transition-colors hover:text-[var(--ow-blue)] hover:decoration-[var(--ow-blue)]",
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
        "ow-session-md-copy-button rounded-lg border border-[var(--ow-line-soft)] bg-[var(--ow-panel)] px-2 py-1 text-[11px] font-semibold text-[var(--ow-disabled)] transition-colors hover:bg-[var(--ow-panel)] hover:text-[var(--ow-inverse)]",
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
        "ow-session-md-code-block my-4 overflow-hidden rounded-xl border border-[var(--ow-line)] bg-[var(--ow-code)] text-[13px] leading-relaxed text-[var(--ow-text)] shadow-inner",
    },
    h(
      "div",
      {
        className:
          "ow-session-md-code-toolbar flex items-center justify-between gap-3 border-b border-[var(--ow-line-soft)] bg-[var(--ow-panel-soft)] px-3 py-2",
      },
      h(
        "span",
        {
          className:
            "ow-session-md-code-lang rounded-md bg-[var(--ow-panel)] px-2 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--ow-subtle)]",
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
          className: joinClassNames("font-mono leading-relaxed text-[var(--ow-text)]", className),
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
          "ow-session-md-inline-code break-words rounded-md border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] px-1.5 py-0.5 font-mono text-[0.9em] font-semibold text-[var(--ow-text)] [box-shadow:var(--ow-shadow-sm)]",
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
        "ow-session-md-table-wrap my-4 overflow-x-auto rounded-2xl border border-[var(--ow-line)] [box-shadow:var(--ow-shadow-sm)]",
    },
    h(
      "table",
      {
        className:
          "ow-session-md-table min-w-full border-collapse bg-[var(--ow-panel)] text-left text-[13px] leading-normal text-[var(--ow-text)]",
      },
      children,
    ),
  );
}

function TableHead({ children }) {
  return h("thead", { className: "ow-session-md-table-head bg-[var(--ow-panel-soft)] text-[var(--ow-muted)]" }, children);
}

function TableHeader({ children }) {
  return h(
    "th",
    {
      className:
        "ow-session-md-table-header border-b border-[var(--ow-line)] px-3 py-2 font-bold first:rounded-tl-2xl last:rounded-tr-2xl",
    },
    children,
  );
}

function TableCell({ children }) {
  return h("td", { className: "ow-session-md-table-cell border-t border-[var(--ow-line-soft)] px-3 py-2 align-top" }, children);
}

export const sessionMarkdownComponents = {
  h1: createHeading(
    "h1",
    "ow-session-md-heading mt-1 mb-3 text-[22px] font-bold leading-tight tracking-[-0.035em] text-[var(--ow-text)]",
  ),
  h2: createHeading(
    "h2",
    "ow-session-md-heading mt-1 mb-3 text-[19px] font-bold leading-tight tracking-[-0.03em] text-[var(--ow-text)]",
  ),
  h3: createHeading(
    "h3",
    "ow-session-md-heading mt-4 mb-2 text-[15px] font-bold leading-snug tracking-[-0.015em] text-[var(--ow-text)]",
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
