import { SessionMarkdownContent } from "../../utils/sessionMarkdown.js";

export function SessionMarkdown({ content }: { content: string }) {
  return (
    <div className="ow-session-markdown text-[15px] text-slate-800">
      <SessionMarkdownContent content={content} />
    </div>
  );
}
