import { lazy, Suspense } from "react";

const SessionMarkdownContent = lazy(() =>
  import("../../utils/sessionMarkdown.js").then((module) => ({
    default: module.SessionMarkdownContent,
  })),
);

export function SessionMarkdown({ content }: { content: string }) {
  return (
    <div className="ow-session-markdown text-[15px] text-[var(--ow-text)]">
      <Suspense
        fallback={
          <div className="grid min-h-10 place-items-center">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--ow-line)] border-t-[var(--ow-blue)]" />
          </div>
        }
      >
        <SessionMarkdownContent content={content} />
      </Suspense>
    </div>
  );
}
