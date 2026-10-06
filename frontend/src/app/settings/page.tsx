"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import type { RiskProfile, V4Profile } from "@/lib/types";
import Card from "@/components/ui/Card";
import { Row } from "@/components/ui/Panel";

// Earlier tools are still available, just no longer part of the daily journey. Each says what it holds.
const FIELD_LABEL: Record<string, string> = {
  monthly_income: "monthly income",
  monthly_essential_expenses: "monthly essential expenses",
  emergency_reserve_amount: "emergency reserve",
  emergency_reserve_months_target: "reserve target in months",
  "tolerance_answers.portfolio_drop_20pct_reaction": "how you would react to a 20% fall",
  "tolerance_answers.priority": "your investing priority",
  "tolerance_answers.loss_tolerance": "the largest fall you could accept",
};
const fieldLabel = (f: string) => FIELD_LABEL[f] ?? f.replace(/[_.]/g, " ");

const EARLIER_TOOLS: { href: string; label: string; what: string }[] = [
  { href: "/dashboard", label: "Earlier research dashboard", what: "Run the earlier Nifty 50 candidate analysis (off unless the research pipeline is enabled)." },
  { href: "/recommendations", label: "Earlier stock candidates", what: "Ranked candidate cards from earlier research runs. Historical and heuristic, not your holdings." },
  { href: "/portfolio", label: "Earlier candidate portfolio", what: "A hypothetical mix for an amount you type. It is an illustration, not what you own." },
  { href: "/goals", label: "Earlier goals", what: "Goals from the first version, funded from the old holdings snapshot. Separate from Goals & SIPs." },
  { href: "/catalogue", label: "Product catalogue", what: "Product terms. Includes demonstration data that is not a real quote." },
  { href: "/safer-alternatives", label: "Safer options", what: "Education on lower-volatility products and their trade-offs." },
];

export default function SettingsPage() {
  const [current, setCurrent] = useState<V4Profile | null | "error">(null);
  const [earlier, setEarlier] = useState<RiskProfile | null>(null);

  useEffect(() => {
    api.get<V4Profile>("/api/v4/profile").then(setCurrent).catch(() => setCurrent("error"));
    // The earlier profile may simply not exist; that is not an error on this page.
    api.get<RiskProfile>("/api/onboarding/me").then(setEarlier).catch(() => setEarlier(null));
  }, []);

  const answered = current && current !== "error" ? current.missing_fields.length === 0 : null;

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Settings</h1>
        <p className="text-sm text-text-muted">Your profile, source connections, how the analysis is checked, and the earlier tools.</p>
      </div>

      <Card title="Financial profile">
        <p className="text-sm text-text-muted">
          This is the profile your portfolio reviews and new-investment plans use: income, spending, reserve, loans, how you
          feel about losses, and anything you do not want to invest in.
        </p>
        <p className="mt-2 text-sm">
          {current === null && <span className="text-text-muted">Checking…</span>}
          {current === "error" && <span className="text-negative">Could not load it just now. Open it to try again.</span>}
          {answered === true && <span className="text-positive">All the questions are answered.</span>}
          {answered === false && current !== "error" && current && (
            <span className="text-warning">Still needed: {current.missing_fields.map(fieldLabel).join(", ")}.</span>
          )}
        </p>
        <Link href="/finances" className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-accent hover:text-accent-hover">
          Open Financial profile <ArrowRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </Card>

      <Card title="Connections">
        <p className="text-sm text-text-muted">
          Angel One is connected from a terminal on this computer, never from this page, and the app only reads from it. If you
          would rather not connect, add each account by CSV or by hand.
        </p>
        <Link href="/holdings" className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-accent hover:text-accent-hover">
          Accounts and connection status <ArrowRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </Card>

      <Card title="Data freshness">
        <p className="text-sm text-text-muted">
          Prices, price history, signals and forecasts update after each trading day&apos;s close, and fund data updates daily. See what is current, what is
          waiting, and when the next update runs.
        </p>
        <Link href="/data" className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-accent hover:text-accent-hover">
          Data freshness <ArrowRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </Card>

      <Card title="About the analysis">
        <p className="text-sm text-text-muted">
          Signals such as trend, volatility and the price forecast are descriptions of past prices. They count for nothing in any
          plan until they have proved themselves against what prices later did. (The stock ranking on Plan new investment is a separate screen built from value, quality and momentum; it does steer which Nifty 50 stocks a plan picks, and is itself untested.) That evidence, and its limits, is on Model
          evidence. It measures the method, not your own returns.
        </p>
        <Link href="/scorecard" className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-accent hover:text-accent-hover">
          Model evidence <ArrowRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </Card>

      <Card title="Earlier tools">
        <p className="text-sm text-text-muted">From the first version of this app. They use their own saved data and do not change your current portfolio review.</p>
        <ul className="mt-3 divide-y divide-border">
          {EARLIER_TOOLS.map((t) => (
            <li key={t.href} className="py-2">
              <Link href={t.href} className="text-sm font-medium text-accent hover:text-accent-hover">{t.label}</Link>
              <p className="text-xs text-text-muted">{t.what}</p>
            </li>
          ))}
        </ul>
        <div className="mt-4 border-t border-border pt-3">
          <h3 className="text-sm font-medium text-text-primary">Earlier investor questionnaire</h3>
          {earlier ? (
            <>
              <p className="mt-1 text-xs text-text-muted">Used only by the earlier stock-candidate research. It is not your Financial profile.</p>
              <dl className="mt-2 space-y-1 capitalize">
                <Row label="Risk profile" value={earlier.risk_profile} />
                <Row label="Horizon" value={`${earlier.investment_horizon_years} years`} />
                <Row label="Objective" value={earlier.objective.replace(/_/g, " ")} />
              </dl>
            </>
          ) : (
            <p className="mt-1 text-xs text-text-muted">Not filled in, and you do not need it for portfolio reviews.</p>
          )}
          <Link href="/onboarding" className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-accent hover:text-accent-hover">
            {earlier ? "Redo the earlier questionnaire" : "Fill in the earlier questionnaire"} <ArrowRight aria-hidden className="h-3.5 w-3.5" />
          </Link>
        </div>
      </Card>
    </div>
  );
}
