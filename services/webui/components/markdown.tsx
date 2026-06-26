"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

// Rendu Markdown des réponses LLM (chat global et projet). Typographie shadcn (prose),
// adaptée au thème (dark) et aux bulles compactes.
export function Markdown({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "prose prose-sm max-w-none dark:prose-invert",
        "prose-pre:bg-background prose-pre:text-foreground prose-pre:border",
        "prose-code:before:content-none prose-code:after:content-none",
        "prose-p:my-1.5 prose-headings:mt-2 prose-headings:mb-1 prose-ul:my-1.5 prose-ol:my-1.5",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: (props) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
