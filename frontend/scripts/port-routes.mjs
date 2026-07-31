import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const pkgRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const routesRoot = path.join(pkgRoot, "..", "frontend", "src", "routes");
const appRoot = path.join(pkgRoot, "src", "app");

const entries = [
  ["register.tsx", "register/page.tsx", "guest"],
  ["onboarding.tsx", "onboarding/page.tsx", "onboarding"],
  ["_app/settings.tsx", "(app)/settings/page.tsx", "app"],
  ["_app/vocabulary.tsx", "(app)/vocabulary/page.tsx", "app"],
  ["_app/writing.tsx", "(app)/writing/page.tsx", "app"],
  ["_app/reader.tsx", "(app)/reader/page.tsx", "app"],
  ["_app/library/index.tsx", "(app)/library/page.tsx", "app"],
  ["_app/library/$id.tsx", "(app)/library/[id]/page.tsx", "app-params"],
  ["_app/search.tsx", "(app)/search/page.tsx", "app"],
  ["_app/analytics.tsx", "(app)/analytics/page.tsx", "app"],
  ["_app/analysis.tsx", "(app)/analysis/page.tsx", "app"],
  ["_app/quiz.tsx", "(app)/quiz/page.tsx", "app"],
  ["_app/flashcards.tsx", "(app)/flashcards/page.tsx", "app"],
  ["_app/tutor.tsx", "(app)/tutor/page.tsx", "tutor"],
  ["_app/tutor.$threadId.tsx", "(app)/tutor/[threadId]/page.tsx", "thread"],
  ["_app/speaking.tsx", "(app)/speaking/page.tsx", "app"],
  ["admin/usage.tsx", "admin/(console)/usage/page.tsx", "app"],
  ["admin/feeds.tsx", "admin/(console)/feeds/page.tsx", "app"],
  ["admin/models.tsx", "admin/(console)/models/page.tsx", "app"],
  ["admin/knowledge-base.tsx", "admin/(console)/knowledge-base/page.tsx", "app"],
];

function portSource(raw, kind) {
  if (kind === "tutor") {
    return `"use client";\n\nimport { TutorView } from "@/components/chat/tutor-view";\n\nexport default function TutorPage() {\n  return <TutorView />;\n}\n`;
  }
  if (kind === "thread") {
    return `"use client";\n\nimport { useParams } from "next/navigation";\nimport { TutorView } from "@/components/chat/tutor-view";\n\nexport default function TutorThreadPage() {\n  const { threadId } = useParams<{ threadId: string }>();\n  return <TutorView threadId={threadId} />;\n}\n`;
  }

  let s = raw;
  s = s.replace(/^import[\s\S]*?from "@tanstack\/react-router";?\r?\n/gm, "");
  s = s.replace(/^import \{ redirectIfStudentAuthed \} from "@\/lib\/route-guards";?\r?\n/gm, "");
  s = s.replace(/^import \{ redirectIfAdminAuthed \} from "@\/lib\/route-guards";?\r?\n/gm, "");
  s = s.replace(/export const Route = createFileRoute[\s\S]*?\);\r?\n\r?\n/gm, "");

  const needsLink = /\bLink\b/.test(s) && !s.includes('from "@/components/router-link"');
  const needsRouter = /\buseNavigate\b/.test(s) || /\bnavigate\(/.test(s);
  const needsParams = /Route\.useParams/.test(s);

  const imports = [];
  if (needsLink || needsRouter) {
    const parts = ["Link", "useRouter"];
    if (needsParams) parts.push("useParams");
    imports.push(`import { ${parts.join(", ")} } from "@/components/router-link";`);
  } else if (needsParams) {
    imports.push(`import { useParams } from "next/navigation";`);
  }

  if (kind === "guest") {
    imports.push(`import { useEffect } from "react";`);
    imports.push(`import { getAccessToken, getAuthPortal, useAuthStore } from "@/lib/auth-store";`);
  }
  if (kind === "onboarding") {
    imports.push(`import { useEffect } from "react";`);
    imports.push(`import { getAccessToken, useAuthStore } from "@/lib/auth-store";`);
  }

  s = s.replace(/^function (\w+)/m, "export default function $1");
  s = s.replace(/\bconst navigate = useNavigate\(\)/g, "const router = useRouter()");
  s = s.replace(/navigate\(\{\s*to:\s*"([^"]+)"(?:,\s*search:\s*\{[^}]+\})?\s*\}\)/g, (_, to) => {
    if (to.includes("admin/login")) return `router.push(\`/admin/login?email=\${encodeURIComponent(email.trim())}\`)`;
    return `router.push("${to}")`;
  });
  s = s.replace(/navigate\(\{\s*to:\s*([^}]+)\s*\}\)/g, "router.push($1)");
  s = s.replace(/const \{ id \} = Route\.useParams\(\)/g, "const { id } = useParams() as { id: string }");
  s = s.replace(/const \{ threadId \} = Route\.useParams\(\)/g, "const { threadId } = useParams() as { threadId: string }");
  s = s.replace(/parsed\.error\.errors/g, "parsed.error.issues");

  const header = `"use client";\n\n${imports.join("\n")}\n\n`;
  s = header + s.trimStart();

  if (kind === "guest") {
    s = s.replace(
      /export default function (\w+)\(\) \{/,
      `export default function $1() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    const token = getAccessToken();
    const portal = getAuthPortal();
    if (token && user && portal === "student") {
      router.replace(user.onboarded ? "/dashboard" : "/onboarding");
    }
  }, [router, user]);
`,
    );
    s = s.replace(/\bconst router = useRouter\(\);\r?\n  const user = useAuthStore[\s\S]*?\}, \[router, user\]\);\r?\n\r?\n  const router = useRouter\(\);/m, "");
  }

  if (kind === "onboarding") {
    s = s.replace(
      /export default function OnboardingPage\(\) \{/,
      `export default function OnboardingPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getAccessToken()) router.replace("/login");
  }, [router]);
`,
    );
    s = s.replace(/\bconst router = useRouter\(\);\r?\n\r?\n  useEffect[\s\S]*?\}, \[router\]\);\r?\n\r?\n  const router = useRouter\(\);/m, "");
    s = s.replace(/\bconst navigate = useRouter\(\)/, "const router = useRouter()");
    s = s.replace(/navigate\(\{ to: "\/tutor" \}\)/, 'router.push("/tutor")');
  }

  if (needsLink && !s.includes('from "@/components/router-link"')) {
    // Link used but only router imported — add Link
    s = s.replace(
      'from "@/components/router-link";',
      'Link, useRouter } from "@/components/router-link";\nimport { useRouter',
    );
  }

  return s;
}

for (const [src, pageRel, kind] of entries) {
  const srcPath = path.join(routesRoot, src);
  if (!fs.existsSync(srcPath)) {
    console.warn("missing", src);
    continue;
  }
  const raw = fs.readFileSync(srcPath, "utf8");
  const out = portSource(raw, kind);
  const pagePath = path.join(appRoot, pageRel);
  fs.mkdirSync(path.dirname(pagePath), { recursive: true });
  fs.writeFileSync(pagePath, out);
  console.log("wrote", pageRel);
}

const voiceDir = path.join(appRoot, "(app)/voice");
fs.mkdirSync(voiceDir, { recursive: true });
fs.writeFileSync(
  path.join(voiceDir, "page.tsx"),
  `import { redirect } from "next/navigation";\n\nexport default function VoicePage() {\n  redirect("/speaking");\n}\n`,
);

console.log("done");
