export default function AdminRootLayout({ children }: { children: React.ReactNode }) {
  // The console used to force the dark "obsidian" tokens with its own boot
  // script. It now follows the SAME stored theme as the learner app (light
  // "classroom" by default) — the root layout's boot script already applies
  // it, and the sidebar offers the same switcher the learner shell has.
  return children;
}
