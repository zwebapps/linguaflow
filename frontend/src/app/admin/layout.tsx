import { AdminTheme } from "@/components/admin/admin-theme";

const ADMIN_THEME_BOOT = `(function(){try{document.documentElement.setAttribute("data-app-theme","obsidian");document.documentElement.style.colorScheme="dark";}catch(e){}})();`;

export default function AdminRootLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: ADMIN_THEME_BOOT }} />
      <AdminTheme>{children}</AdminTheme>
    </>
  );
}
