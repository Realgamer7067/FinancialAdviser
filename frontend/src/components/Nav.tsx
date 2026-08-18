"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { clearToken, getToken } from "@/lib/api";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/recommendations", label: "Recommendations" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/safer-alternatives", label: "Safer Options" },
  { href: "/settings", label: "Settings" },
];

export default function Nav() {
  const router = useRouter();
  // Server render has no access to localStorage, so start logged-out and
  // sync after mount -- avoids a hydration mismatch (Section 71 note: this
  // is a UI concern, not a data-integrity one).
  const [loggedIn, setLoggedIn] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => {
    setLoggedIn(!!getToken());
  }, []);

  function logout() {
    clearToken();
    router.push("/");
  }

  return (
    <nav className="border-b bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <Link href="/" className="font-semibold text-brand-700">
          Indian Equity Research
        </Link>
        {loggedIn && (
          <>
            <div className="hidden items-center gap-4 text-sm sm:flex">
              {links.map((l) => (
                <Link key={l.href} href={l.href} className="text-slate-600 hover:text-brand-700">
                  {l.label}
                </Link>
              ))}
              <button onClick={logout} className="text-slate-400 hover:text-red-600">
                Log out
              </button>
            </div>
            <button
              onClick={() => setMobileOpen((o) => !o)}
              aria-label="Toggle menu"
              className="rounded border px-2 py-1 text-slate-600 sm:hidden"
            >
              {mobileOpen ? "✕" : "☰"}
            </button>
          </>
        )}
      </div>
      {loggedIn && mobileOpen && (
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
          <button onClick={logout} className="text-left text-slate-400 hover:text-red-600">
            Log out
          </button>
        </div>
      )}
    </nav>
  );
}
