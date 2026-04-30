import { memo, useEffect, useState } from "react";
import type { BundledLanguage, Highlighter } from "shiki";

let highlighterPromise: Promise<Highlighter> | null = null;

function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = import("shiki").then((shiki) =>
      shiki.createHighlighter({
        themes: ["github-dark"],
        langs: ["bash", "python", "typescript", "javascript", "json", "yaml", "markdown", "diff"],
      }),
    );
  }
  return highlighterPromise;
}

const LANG_MAP: Record<string, string> = {
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  py: "python",
  yml: "yaml",
  md: "markdown",
};

function detectLanguage(code: string, hint?: string): string {
  if (hint) {
    const normalized = hint.toLowerCase();
    return LANG_MAP[normalized] ?? normalized;
  }
  if (code.startsWith("$ ") || code.startsWith("#!")) return "bash";
  if (code.includes("def ") || code.includes("import ")) return "python";
  if (code.includes("function ") || code.includes("const ")) return "typescript";
  return "bash";
}

interface CodeBlockProps {
  code: string;
  language?: string;
  maxHeight?: number;
}

export const CodeBlock = memo(function CodeBlock({
  code,
  language,
  maxHeight = 300,
}: CodeBlockProps) {
  const [html, setHtml] = useState<string | null>(null);
  const lang = detectLanguage(code, language);

  useEffect(() => {
    let cancelled = false;
    getHighlighter()
      .then((highlighter) => {
        if (cancelled) return;
        const supportedLangs = highlighter.getLoadedLanguages();
        const effectiveLang = supportedLangs.includes(lang as BundledLanguage) ? lang : "bash";
        const result = highlighter.codeToHtml(code, {
          lang: effectiveLang,
          theme: "github-dark",
        });
        setHtml(result);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [code, lang]);

  if (!html) {
    return (
      <pre
        className="text-[11px] font-mono whitespace-pre-wrap overflow-auto bg-background rounded p-2"
        style={{ maxHeight }}
      >
        {code}
      </pre>
    );
  }

  return (
    <div
      className="text-[11px] overflow-auto rounded [&_pre]:p-2 [&_pre]:m-0 [&_pre]:bg-background!"
      style={{ maxHeight }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
});
