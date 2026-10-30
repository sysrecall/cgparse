import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Fira_Sans, Poppins } from "next/font/google";

import { Footer } from "@/components/Footer";
import { Nav } from "@/components/Nav";

import "./globals.css";

const poppins = Poppins({
  variable: "--font-poppins",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  display: "swap",
});

const firaSans = Fira_Sans({
  variable: "--font-fira",
  subsets: ["latin"],
  weight: ["300", "400", "500", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "CareGuide · Document Intelligence",
    template: "%s · CareGuide",
  },
  description:
    "AI-powered ingestion, extraction, validation and search for financial documents. No invented data — uncertain values land in a human review queue.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${poppins.variable} ${firaSans.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col bg-surface text-body">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-white"
        >
          Skip to content
        </a>
        <Nav />
        <main id="main" className="flex-1">
          {children}
        </main>
        <Footer />
      </body>
    </html>
  );
}
