import type { Metadata } from "next";
import { DM_Serif_Display, Inter } from "next/font/google";
import { QueryProvider } from "./lib/queryClient";
import "./globals.css";

// Both self-hosted by Next.js at build time (no runtime call to Google
// Fonts, no new npm dependency, both free/open-license families) —
// Inter for all application UI, DM Serif Display reserved for the small
// number of real headline moments (see globals.css's --font-serif).
const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const dmSerifDisplay = DM_Serif_Display({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-serif",
});

export const metadata: Metadata = {
  title: "AgentOps AI",
  description: "AgentOps AI Platform",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${dmSerifDisplay.variable}`}>
      <body className="font-sans">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
