"use client";

import { useState } from "react";
import Link from "next/link";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/recommendations", label: "Recommendations" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/compare", label: "Compare" },
  { href: "/planning", label: "Planner" },
  { href: "/safer-alternatives", label: "Safer Options" },
  { href: "/settings", label: "Settings" },
];

export default function Nav() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <nav className="border-b bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <Link href="/" className="font-semibold text-brand-700">
          Indian Equity Research
        </Link>
        <div className="hidden items-center gap-4 text-sm sm:flex">
          {links.map((l) => (
            <Link key={l.href} href={l.href} className="text-slate-600 hover:text-brand-700">
              {l.label}
            </Link>
          ))}
        </div>
        <button
          onClick={() => setMobileOpen((o) => !o)}
          aria-label="Toggle menu"
          className="rounded border px-2 py-1 text-slate-600 sm:hidden"
        >
          {mobileOpen ? "✕" : "☰"}
        </button>
      </div>
      {mobileOpen && (
        <div className="flex flex-col gap-2 border-t bg-white px-4 py-3 text-sm sm:hidden">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="text-slate-600 hover:text-brand-700"
              onClick={() => setMobileOpen(false)}
            >
              {l.label}
            </Link>
          ))}
        </div>
      )}
    </nav>
  );
}
