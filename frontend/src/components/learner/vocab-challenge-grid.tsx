import type { VocabItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const CHUNK = 5;

export function VocabChallengeGrid({ items }: { items: VocabItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--worksheet-muted)" }}>
        Save words from Reader or the tutor to fill your challenge grid.
      </p>
    );
  }

  const groups: VocabItem[][] = [];
  for (let i = 0; i < items.length; i += CHUNK) {
    groups.push(items.slice(i, i + CHUNK));
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {groups.map((group, dayIndex) => (
        <div
          key={dayIndex}
          className={cn(
            "overflow-hidden rounded-lg border border-[color-mix(in_srgb,var(--worksheet-line)_80%,transparent)] bg-[var(--worksheet-card)] shadow-sm",
            `vocab-card-accent-${dayIndex % 6}`,
          )}
        >
          <div
            className="vocab-day-header px-3 py-2 font-semibold text-[var(--worksheet-fg)]"
            style={{ backgroundColor: "var(--vocab-strip)" }}
          >
            Set {dayIndex + 1}
          </div>
          <ul className="space-y-2 px-3 py-3 text-sm">
            {group.map((v) => (
              <li key={v.id} className="flex flex-col gap-0.5 border-b border-[color-mix(in_srgb,var(--worksheet-line)_40%,transparent)] pb-2 last:border-0 last:pb-0">
                <span className="font-medium text-[var(--worksheet-fg)]">{v.lemma}</span>
                {v.meaning && (
                  <span className="text-xs" style={{ color: "var(--worksheet-muted)" }}>
                    {v.meaning}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function VocabHowToUse() {
  const steps = [
    { n: 1, title: "Learn", hint: "Read definitions in your list below." },
    { n: 2, title: "Speak", hint: "Say each word out loud a few times." },
    { n: 3, title: "Write", hint: "One German sentence per word." },
    { n: 4, title: "Use", hint: "Drop a word into chat or writing practice." },
  ];

  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {steps.map((s) => (
        <div
          key={s.n}
          className="rounded-lg border border-[color-mix(in_srgb,var(--worksheet-line)_70%,transparent)] bg-[color-mix(in_srgb,var(--worksheet-card)_90%,transparent)] p-3"
        >
          <p className="font-mono text-xs font-semibold" style={{ color: "var(--worksheet-accent)" }}>
            {s.n}. {s.title}
          </p>
          <p className="mt-1 text-xs" style={{ color: "var(--worksheet-muted)" }}>
            {s.hint}
          </p>
        </div>
      ))}
    </div>
  );
}
