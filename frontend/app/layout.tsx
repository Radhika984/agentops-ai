import type { Metadata } from "next";
import { DM_Serif_Display, Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import { QueryProvider } from "./lib/queryClient";
import "./globals.css";

// All self-hosted by Next.js at build time (no runtime call to Google
// Fonts, no new npm dependency, all free/open-license families).
//
// "Espresso Ink" redesign (v2 brief): Geist replaces Inter as the UI
// sans everywhere; Geist Mono replaces JetBrains Mono for IDs/hashes/
// version labels/tool names/JSON (--font-mono). The display serif is
// scoped, not global: DM Serif Display remains the public landing page's
// brand face (its own light palette/identity is untouched), while
// Instrument Serif serves two separate scoped identities — the
// authenticated app (globals.css's `.app-canvas` block, which overrides
// the shared --font-serif variable so every existing `font-serif`/
// `text-display` usage there picks it up automatically) and the
// register/login "Intelligence Field" screens (`.signup-canvas`'s
// `.font-instrument` utility, referenced directly rather than through
// --font-serif).
const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });
const dmSerifDisplay = DM_Serif_Display({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-serif",
});
const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument-serif",
});
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "AgentOps AI",
  description: "AgentOps AI Platform",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geist.variable} ${dmSerifDisplay.variable} ${instrumentSerif.variable} ${geistMono.variable}`}
    >
      <body className="font-sans">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
