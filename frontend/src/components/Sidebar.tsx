"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import clsx from "clsx";
import {
  Calculator,
  FlaskConical,
  GitCompare,
  LayoutDashboard,
  Library,
  ListChecks,
  Menu,
  PieChart,
  Settings,
  ShieldCheck,
  Target,
  Wallet,
  X,
} from "lucide-react";

const LINKS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/recommendations", label: "Recommendations", icon: ListChecks },
  { href: "/portfolio", label: "Portfolio", icon: PieChart },
  { href: "/holdings", label: "Holdings", icon: Wallet },
  { href: "/goals", label: "Goals", icon: Target },
  { href: "/catalogue", label: "Catalogue", icon: Library },
  { href: "/compare", label: "Compare", icon: GitCompare },
  { href: "/planning", label: "Planner", icon: Calculator },
  { href: "/research", label: "Research", icon: FlaskConical },
  { href: "/safer-alternatives", label: "Safer Options", icon: ShieldCheck },
  { href: "/settings", label: "Settings", icon: Settings },
];

function NavLinks({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <nav className="flex flex-1 flex-col gap-1 px-3">
      {LINKS.map((l) => {
        const active = pathname === l.href || pathname.startsWith(l.href + "/");
        const Icon = l.icon;
        return (
          <Link
            key={l.href}
            href={l.href}
            onClick={onNavigate}
            className={clsx(
              "relative flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
              active ? "bg-sidebar-hover font-medium text-sidebar-active-text" : "text-sidebar-text-muted hover:bg-sidebar-hover/60 hover:text-sidebar-text"
            )}
          >
            {active && (
              <motion.span
                layoutId="sidebar-active-indicator"
                className="absolute -left-3 h-5 w-0.5 rounded-full bg-indigo-400"
                transition={{ duration: 0.2 }}
              />
            )}
            <Icon className="h-4 w-4 shrink-0" />
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <>
      {/* Desktop: fixed left rail -- dark indigo surface, deliberately distinct
          from the light content area for contrast/hierarchy. */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-56 flex-col bg-sidebar-bg sm:flex">
        <Link href="/" className="flex items-center gap-2 px-4 py-4 font-display font-semibold text-sidebar-active-text">
          Indian Equity Research
        </Link>
        <NavLinks pathname={pathname} />
        <p className="px-6 py-4 text-[11px] text-sidebar-text-muted">Cached data only — no live feed</p>
      </aside>

      {/* Mobile: top bar + slide-in drawer */}
      <div className="flex items-center justify-between bg-sidebar-bg px-4 py-3 sm:hidden">
        <Link href="/" className="font-display font-semibold text-sidebar-active-text">
          Indian Equity Research
        </Link>
        <button
          onClick={() => setMobileOpen(true)}
          aria-label="Open menu"
          className="rounded-md border border-sidebar-hover p-1.5 text-sidebar-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <Menu className="h-4 w-4" />
        </button>
      </div>

      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileOpen(false)}
              className="fixed inset-0 z-40 bg-black/50 sm:hidden"
            />
            <motion.aside
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-sidebar-bg pt-4 shadow-md sm:hidden"
            >
              <div className="mb-2 flex items-center justify-between px-4">
                <span className="font-display font-semibold text-sidebar-active-text">Menu</span>
                <button
                  onClick={() => setMobileOpen(false)}
                  aria-label="Close menu"
                  className="rounded-md border border-sidebar-hover p-1.5 text-sidebar-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <NavLinks pathname={pathname} onNavigate={() => setMobileOpen(false)} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
