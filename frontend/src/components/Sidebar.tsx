"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import clsx from "clsx";
import {
  Calculator,
  Landmark,
  Scale,
  Inbox,
  BookOpenCheck,
  Eye,
  Gauge,
  Activity,
  CalendarClock,
  Database,
  FlaskConical,
  GitCompare,
  LayoutDashboard,
  ListChecks,
  Menu,
  PiggyBank,
  Settings,
  Store,
  Wallet,
  X,
} from "lucide-react";

type NavItem = { href: string; label: string; icon: typeof Wallet };
type NavGroup = { heading: string | null; items: NavItem[] };

// Four domains plus utilities (UI audit R01). Routes are unchanged; only labels and grouping moved,
// because other pages and tests link to these paths. The earlier research tools live under Settings.
export const NAV_GROUPS: NavGroup[] = [
  { heading: null, items: [{ href: "/overview", label: "Overview", icon: LayoutDashboard }] },
  {
    heading: "Portfolio",
    items: [
      { href: "/holdings", label: "Holdings", icon: Wallet },
      { href: "/risk", label: "Risk & exposure", icon: Activity },
      { href: "/actions", label: "Portfolio review", icon: ListChecks },
      { href: "/allocate", label: "Plan new investment", icon: PiggyBank },
      { href: "/simulate", label: "Compare a change", icon: Scale },
    ],
  },
  {
    heading: "Planning",
    items: [
      { href: "/plan", label: "Goals & SIPs", icon: CalendarClock },
      { href: "/finances", label: "Financial profile", icon: Landmark },
      { href: "/planning", label: "Calculators", icon: Calculator },
    ],
  },
  {
    heading: "Explore",
    items: [
      { href: "/market", label: "Market", icon: Store },
      { href: "/watchlist", label: "Watchlists", icon: Eye },
      { href: "/research", label: "Research", icon: FlaskConical },
      { href: "/theses", label: "Investment rationales", icon: BookOpenCheck },
      { href: "/compare", label: "Compare stocks", icon: GitCompare },
    ],
  },
  {
    heading: "Utilities",
    items: [
      { href: "/inbox", label: "Attention", icon: Inbox },
      { href: "/data", label: "Data freshness", icon: Database },
      { href: "/scorecard", label: "Model evidence", icon: Gauge },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

function isActive(pathname: string, href: string) {
  // /plan must not light up for /planning
  return pathname === href || pathname.startsWith(href + "/");
}

function NavLinks({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-3 pb-2" aria-label="Main">
      {NAV_GROUPS.map((g, gi) => (
        <div key={g.heading ?? "top"} className={gi === 0 ? "" : "mt-4"}>
          {g.heading && (
            <p className="mb-1 px-3 text-[11px] font-medium uppercase tracking-wide text-sidebar-text-muted">{g.heading}</p>
          )}
          {g.items.map((l) => {
            const active = isActive(pathname, l.href);
            const Icon = l.icon;
            return (
              <Link
                key={l.href}
                href={l.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={clsx(
                  "relative flex items-center gap-2.5 rounded-md px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300",
                  active ? "bg-sidebar-hover font-medium text-sidebar-active-text" : "text-sidebar-text hover:bg-sidebar-hover/60 hover:text-sidebar-active-text"
                )}
              >
                {active && <span aria-hidden className="absolute -left-3 h-5 w-0.5 rounded-full bg-indigo-400" />}
                <Icon aria-hidden className="h-4 w-4 shrink-0" />
                {l.label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  // Drawer focus: move into it on open, Escape closes, focus returns to the trigger.
  useEffect(() => {
    if (!mobileOpen) return;
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMobileOpen(false);
        menuButton.current?.focus();
      }
      if (e.key === "Tab") {
        // Keep Tab inside the open menu: the page behind it is covered and must not take focus.
        const items = Array.from(document.querySelectorAll<HTMLElement>("#mobile-menu a[href], #mobile-menu button"));
        if (items.length === 0) return;
        const first = items[0], last = items[items.length - 1];
        const active = document.activeElement;
        if (e.shiftKey && (active === first || !items.includes(active as HTMLElement))) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && (active === last || !items.includes(active as HTMLElement))) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  return (
    <>
      {/* Desktop: fixed left rail -- dark indigo surface, deliberately distinct
          from the light content area for contrast/hierarchy. */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-56 flex-col bg-sidebar-bg sm:flex">
        <Link href="/" className="flex items-center gap-2 px-4 py-4 font-display font-semibold text-sidebar-active-text">
          Portfolio Intelligence
        </Link>
        <NavLinks pathname={pathname} />
        <p className="px-6 py-4 text-[11px] text-sidebar-text-muted">Read-only · you place every order yourself</p>
      </aside>

      {/* Mobile: top bar + slide-in drawer */}
      <header className="flex items-center justify-between bg-sidebar-bg px-4 py-3 sm:hidden">
        <Link href="/" className="font-display font-semibold text-sidebar-active-text">
          Portfolio Intelligence
        </Link>
        <button
          ref={menuButton}
          aria-expanded={mobileOpen}
          aria-controls="mobile-menu"
          onClick={() => setMobileOpen(true)}
          aria-label="Open menu"
          className="rounded-md border border-sidebar-hover p-1.5 text-sidebar-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <Menu className="h-4 w-4" />
        </button>
      </header>

      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              aria-hidden
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileOpen(false)}
              className="fixed inset-0 z-40 bg-black/50 sm:hidden"
            />
            <motion.aside
              id="mobile-menu"
              role="dialog"
              aria-modal="true"
              aria-label="Menu"
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-sidebar-bg pt-4 shadow-md sm:hidden"
            >
              <div className="mb-2 flex items-center justify-between px-4">
                <span className="font-display font-semibold text-sidebar-active-text">Menu</span>
                <button
                  ref={closeButton}
                  onClick={() => { setMobileOpen(false); menuButton.current?.focus(); }}
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
