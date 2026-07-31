import type { ReactNode } from "react";
import { BookOpenText } from "lucide-react";
import type { ReaderThemeId } from "@/lib/reader-themes";
import { cn } from "@/lib/utils";

export function ReaderArticlePage({
  theme,
  fontSizePx,
  title,
  level,
  paragraphs,
  footer,
  className,
  renderParagraph,
}: {
  theme: ReaderThemeId;
  fontSizePx: number;
  title: string;
  level?: string;
  paragraphs: string[];
  footer?: ReactNode;
  className?: string;
  renderParagraph?: (text: string, index: number) => ReactNode;
}) {
  const themeClass =
    theme === "reader-sepia" ? "reader-sepia" : theme === "reader-midnight" ? "reader-midnight" : "reader-forest";

  return (
    <article
      className={cn(
        themeClass,
        "reader-article overflow-hidden rounded-xl border border-border",
        className,
      )}
      style={{ backgroundColor: "var(--reader-bg)", color: "var(--reader-fg)" }}
    >
      <header className="reader-article-header border-b px-5 py-6 sm:px-8 sm:py-8">
        <p
          className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em]"
          style={{ color: "var(--reader-accent)" }}
        >
          <BookOpenText className="mr-2 inline size-3" />
          {level ? `Kurzgeschichte · ${level}` : "Reading"}
        </p>
        <h1 className="font-display text-2xl font-semibold sm:text-3xl md:text-4xl">{title}</h1>
      </header>

      <div className="reader-article-body mx-auto max-w-[62ch] px-5 py-8 sm:px-8 md:py-12">
        <div className="space-y-6" style={{ fontSize: `${fontSizePx}px`, lineHeight: 1.85 }}>
          {paragraphs.map((p, i) =>
            renderParagraph ? (
              <div key={i}>{renderParagraph(p, i)}</div>
            ) : (
              <p key={i}>{p}</p>
            ),
          )}
        </div>
        {footer && (
          <div
            className="mt-12 border-t pt-5 font-mono text-xs"
            style={{ borderColor: "var(--reader-accent)", color: "var(--reader-accent)" }}
          >
            {footer}
          </div>
        )}
      </div>
    </article>
  );
}
