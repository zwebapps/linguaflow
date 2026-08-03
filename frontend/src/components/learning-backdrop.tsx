/**
 * Decorative language-learning backdrop — original inline SVG, no external
 * images. Speech bubbles, a book, umlaut letters and article chips float at
 * low opacity behind the content, the way learning apps dress their empty
 * space. Colors ride the theme tokens (currentColor on a muted wrapper), so
 * the art works in Vitality, Midnight and Forest alike.
 *
 * Purely cosmetic: aria-hidden, pointer-events-none, sits in a passed
 * className's stacking context (give the parent `relative` and the content
 * `relative z-10`).
 */
export function LearningBackdrop({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute inset-0 overflow-hidden text-primary ${className}`}
    >
      <svg
        className="absolute -right-8 -top-6 size-48 opacity-[0.07]"
        viewBox="0 0 120 120"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* speech bubble saying Hallo! */}
        <path d="M18 24h84a8 8 0 0 1 8 8v40a8 8 0 0 1-8 8H50l-16 16v-16H18a8 8 0 0 1-8-8V32a8 8 0 0 1 8-8Z" />
        <text x="32" y="60" fontSize="22" fill="currentColor" stroke="none" fontFamily="inherit">
          Hallo!
        </text>
      </svg>

      <svg
        className="absolute -left-10 bottom-10 size-56 opacity-[0.06]"
        viewBox="0 0 140 120"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* open book */}
        <path d="M70 30c-10-8-26-10-40-10v70c14 0 30 2 40 10 10-8 26-10 40-10V20c-14 0-30 2-40 10Z" />
        <path d="M70 30v70" />
        <path d="M42 42c8 0 16 1 22 4M42 58c8 0 16 1 22 4M98 42c-8 0-16 1-22 4M98 58c-8 0-16 1-22 4" />
      </svg>

      <div className="absolute right-16 top-1/2 -translate-y-1/2 select-none font-display text-8xl font-semibold opacity-[0.05]">
        ä ö ü
      </div>

      <div className="absolute bottom-8 right-1/4 flex select-none gap-3 opacity-[0.08]">
        {["der", "die", "das"].map((a) => (
          <span key={a} className="rounded-full border-2 border-current px-4 py-1 font-mono text-sm">
            {a}
          </span>
        ))}
      </div>

      <svg
        className="absolute left-1/3 top-8 size-24 rotate-12 opacity-[0.06]"
        viewBox="0 0 100 100"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* graduation cap */}
        <path d="M50 22 8 42l42 20 42-20-42-20Z" />
        <path d="M28 52v18c0 6 10 12 22 12s22-6 22-12V52" />
        <path d="M92 42v22" />
      </svg>
    </div>
  );
}
