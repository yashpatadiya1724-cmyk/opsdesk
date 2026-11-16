import type { Metadata } from "next";
import "./globals.css";
import { UserProvider } from "@/context/UserContext";
import { TopNav } from "@/components/TopNav";

export const metadata: Metadata = {
  title: "OpsDesk - B2B Travel Operations Dispatcher",
  description: "Deterministic B2B travel operations platform with LCD-aware SLA routing and AI triage.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        <UserProvider>
          <TopNav />
          <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
            {children}
          </main>
        </UserProvider>
      </body>
    </html>
  );
}
