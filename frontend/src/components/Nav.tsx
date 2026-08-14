"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { clearToken, getToken } from "@/lib/api";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/recommendations", label: "Recommendations" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/settings", label: "Settings" },
];

export default function Nav() {
  const router = useRouter();
  // Server render has no access to localStorage, so start logged-out and
  // sync after mount -- avoids a hydration mismatch (Section 71 note: this
  // is a UI concern, not a data-integrity one).
  const [loggedIn, setLoggedIn] = useState(false);
  useEffect(() => {
    setLoggedIn(!!getToken());
  }, []);

  return (
    <nav className="border-b bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <Link href="/" className="font-semibold text-brand-700">
          Indian Equity Research
        </Link>
        {loggedIn && (
          <div className="flex items-center gap-4 text-sm">
            {links.map((l) => (
              <Link key={l.href} href={l.href} className="text-slate-600 hover:text-brand-700">
                {l.label}
              </Link>
            ))}
            <button
              onClick={() => {
                clearToken();
                router.push("/");
              }}
              className="text-slate-400 hover:text-red-600"
            >
              Log out
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
