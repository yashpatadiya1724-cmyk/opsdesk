import type { Metadata } from "next";
import { DM_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { UserProvider } from "@/context/UserContext";
import { ToastProvider } from "@/context/ToastContext";
import { TopNav, Sidebar } from "@/components/shell";
import { CommandPalette } from "@/components/CommandPalette";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  weight: ["400", "500", "600"],
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "OpsDesk - B2B Travel Operations Dispatcher",
  description: "Calm mission control for travel operations with LCD-aware SLA routing and AI triage.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${dmSans.variable} ${ibmPlexMono.variable}`}
    >
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
(function() {
  try {
    var stored = localStorage.getItem('opsdesk_theme');
    var isDark = false;
    if (stored === 'dark') {
      isDark = true;
    } else if (stored === 'light') {
      isDark = false;
    } else {
      isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    }
    if (isDark) {
      document.documentElement.setAttribute('data-theme', 'dark');
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.setAttribute('data-theme', 'light');
      document.documentElement.classList.remove('dark');
    }
  } catch (e) {}
})();
`,
          }}
        />
      </head>
      <body className="min-h-screen bg-canvas text-content-primary antialiased font-sans flex flex-col selection:bg-brand-50 selection:text-brand-orange-text">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:px-4 focus:py-2 focus:bg-brand-500 focus:text-white focus:rounded-full focus:shadow-md focus:outline-none font-medium text-caption"
        >
          Skip to main content
        </a>
        <UserProvider>
          <ToastProvider>
            <TopNav />
            <CommandPalette />
            <div className="flex-1 flex w-full max-w-[1440px] mx-auto px-4 sm:px-6 gap-4">
              <Sidebar className="sticky top-20 self-start" />
              <main
                id="main-content"
                tabIndex={-1}
                className="flex-1 py-4 overflow-x-hidden min-w-0 outline-none"
              >
                {children}
              </main>
            </div>
          </ToastProvider>
        </UserProvider>
      </body>
    </html>
  );
}
