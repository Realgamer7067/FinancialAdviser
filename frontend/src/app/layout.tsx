import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-display" });

export const metadata: Metadata = {
  title: "Indian AI Equity Research Platform",
  description: "Evidence-grounded Indian equity research for beginner investors.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${spaceGrotesk.variable}`}>
      <body className="font-sans">
        <Sidebar />
        <div className="sm:pl-56">
          <TopBar />
          <main className="px-4 py-6 sm:px-6 sm:py-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
