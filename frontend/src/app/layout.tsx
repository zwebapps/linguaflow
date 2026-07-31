import type { Metadata } from "next";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "LinguaFlow",
  description: "AI-native language learning — tutor, library, speaking, and progress tracking",
};

const APP_THEME_BOOT = `(function(){try{var t=localStorage.getItem("df-app-theme")||"classroom";document.documentElement.setAttribute("data-app-theme",t);}catch(e){document.documentElement.setAttribute("data-app-theme","classroom");}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-app-theme="classroom" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: APP_THEME_BOOT }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=DM+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap"
        />
        <link rel="icon" href="/globe.svg" type="image/svg+xml" />
      </head>
      <body className="min-h-screen antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
