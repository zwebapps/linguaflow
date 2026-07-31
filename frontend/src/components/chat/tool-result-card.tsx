import type { ChatUsage } from "@/lib/types";

export function ToolResultCard({ name, result }: { name: string; result: unknown }) {
  const r = result as Record<string, unknown>;

  if (name === "conjugate_verb" && r.forms && typeof r.forms === "object") {
    const forms = r.forms as Record<string, string>;
    return (
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full font-mono text-xs">
          <tbody>
            {Object.entries(forms).map(([person, form]) => (
              <tr key={person} className="border-b border-border last:border-0">
                <td className="px-3 py-2 text-muted-foreground">{person}</td>
                <td className="px-3 py-2">{form}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (name === "lookup_word") {
    return (
      <div className="rounded-md border border-border p-3 text-sm">
        <p className="font-display font-semibold">{String(r.lemma ?? "")}</p>
        <p className="font-mono text-xs text-muted-foreground">{String(r.ipa ?? "")}</p>
      </div>
    );
  }

  if (name === "search_knowledge_base" && Array.isArray(r.results)) {
    return (
      <p className="text-sm text-muted-foreground">
        {r.results.length} {r.results.length === 1 ? "match" : "matches"} in your library
      </p>
    );
  }

  return (
    <pre className="overflow-x-auto rounded-md bg-background/60 p-3 font-mono text-xs text-muted-foreground">
      {JSON.stringify(result, null, 2)}
    </pre>
  );
}
