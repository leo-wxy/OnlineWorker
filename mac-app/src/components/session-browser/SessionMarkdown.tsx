import { lazy, Suspense } from "react";

const SessionMarkdownContent = lazy(() =>
  import("../../utils/sessionMarkdown.js").then((module) => ({
    default: module.SessionMarkdownContent,
  })),
);

export function SessionMarkdown({ content }: { content: string }) {
  return (
    <div className="ow-session-markdown text-[15px] text-slate-800">
      <Suspense
        fallback={
          <div className="grid min-h-10 place-items-center">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-blue-600" />
          </div>
        }
      >
        <SessionMarkdownContent content={content} />
      </Suspense>
    </div>
  );
}
