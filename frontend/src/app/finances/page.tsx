"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { V4Facts, V4Liability, V4Preference, V4Profile, V4RiskConstraints } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";

const INPUT =
  "mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

const MONEY_FIELDS: { key: keyof V4Facts; label: string; hint?: string }[] = [
  { key: "monthly_income", label: "Monthly income (₹)" },
  { key: "monthly_essential_expenses", label: "Monthly essential expenses (₹)", hint: "rent, food, bills and other must-pay costs. Leave out loan EMIs you record under Loans below; they are added for you." },
  { key: "emergency_reserve_amount", label: "Emergency reserve you hold (₹)", hint: "accessible cash you have set aside, not your whole savings" },
  { key: "emergency_reserve_months_target", label: "Reserve target (months of essential outgo)" },
  { key: "monthly_investable_surplus", label: "Monthly amount you can invest (₹)", hint: "you confirm this; we never guess it" },
  { key: "one_time_available", label: "One-time amount available (₹)" },
];

const TOLERANCE_QUESTIONS: { key: keyof V4Facts["tolerance_answers"]; label: string; options: [string, string][] }[] = [
  { key: "portfolio_drop_20pct_reaction", label: "If your portfolio fell 20%, you would…", options: [["sell_all", "Sell everything"], ["sell_some", "Sell some"], ["hold", "Hold"], ["buy_more", "Buy more"]] },
  { key: "priority", label: "Your priority is…", options: [["capital_preservation", "Protect my capital"], ["balanced_growth", "Balanced growth"], ["maximum_growth", "Maximum growth"]] },
  { key: "loss_tolerance", label: "The largest fall you could accept…", options: [["0_10", "0-10%"], ["10_20", "10-20%"], ["20_30", "20-30%"], ["30_50", "30-50%"], ["50_plus", "More than 50%"]] },
];

function rupees(v: string | null): string {
  if (v === null) return "unknown";
  const n = Number(v);
  return Number.isNaN(n) ? "unknown" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function toNullable(s: string): string | null {
  const t = s.trim();
  return t === "" ? null : t;
}

export default function FinancesPage() {
  const [profile, setProfile] = useState<V4Profile | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liabilities, setLiabilities] = useState<V4Liability[]>([]);
  const [prefs, setPrefs] = useState<V4Preference[]>([]);
  const [constraints, setConstraints] = useState<V4RiskConstraints | null>(null);
  const [liab, setLiab] = useState({ kind: "home_loan", outstanding_amount: "", monthly_payment: "", rate_type: "unknown", next_reset_date: "" });
  const [pref, setPref] = useState({ kind: "exclude_sector", value: "", confirmed: false });
  const [busy, setBusy] = useState(false);

  // `resetForm` is true only for the first load and after a version conflict. Adding a loan or a restriction refreshes
  // everything else but never overwrites what you have typed and not yet saved.
  const load = useCallback(async (resetForm = true) => {
    try {
      const [p, l, pr, rc] = await Promise.all([
        api.get<V4Profile>("/api/v4/profile"),
        api.get<V4Liability[]>("/api/v4/liabilities"),
        api.get<V4Preference[]>("/api/v4/preferences"),
        api.get<V4RiskConstraints>("/api/v4/risk-constraints"),
      ]);
      setConstraints(rc);
      setProfile(p);
      setLiabilities(l);
      setPrefs(pr);
      if (!resetForm) return;
      const f = p.facts;
      setForm({
        ...Object.fromEntries(MONEY_FIELDS.map((m) => [m.key, (f[m.key] as string | null) ?? ""])),
        income_stability: f.income_stability ?? "",
        dependents: f.dependents === null ? "" : String(f.dependents),
        knowledge_level: f.knowledge_level ?? "",
        employer_exposure: f.employer_exposure ?? "",
        ...Object.fromEntries(TOLERANCE_QUESTIONS.map((q) => [q.key, f.tolerance_answers[q.key] ?? ""])),
      });
    } catch (e) {
      setError(errMsg(e, "Failed to load"));
    }
  }, []);

  useEffect(() => {
    load(true);
  }, [load]);

  async function save() {
    if (!profile) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    const facts = {
      ...Object.fromEntries(MONEY_FIELDS.map((m) => [m.key, toNullable(form[m.key] ?? "")])),
      income_stability: toNullable(form.income_stability ?? ""),
      dependents: toNullable(form.dependents ?? "") === null ? null : Number(form.dependents),
      knowledge_level: toNullable(form.knowledge_level ?? ""),
      employer_exposure: toNullable(form.employer_exposure ?? ""),
      near_term_obligations: profile.facts.near_term_obligations,
      tolerance_answers: Object.fromEntries(TOLERANCE_QUESTIONS.map((q) => [q.key, toNullable(form[q.key] ?? "")])),
    };
    try {
      const p = await api.put<V4Profile>("/api/v4/profile", { expected_version: profile.version, facts });
      setProfile(p);
      await load(false);   // limits and capacity below are recomputed from what was just saved
      setMsg("Saved. The summary below now reflects these answers.");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError("Your finances were changed somewhere else, so nothing was saved. The newest saved values are loaded; check them and save again.");
        load(true);
      } else setError(errMsg(e, "Could not save"));
    } finally {
      setBusy(false);
    }
  }

  async function addLiability() {
    setError(null);
    try {
      await api.post("/api/v4/liabilities", {
        kind: liab.kind,
        outstanding_amount: liab.outstanding_amount,
        as_of: new Date().toISOString().slice(0, 10),
        monthly_payment: toNullable(liab.monthly_payment),
        rate_type: liab.rate_type,
        next_reset_date: toNullable(liab.next_reset_date),
      });
      setLiab({ ...liab, outstanding_amount: "", monthly_payment: "", next_reset_date: "" });
      load(false);
    } catch (e) {
      setError(errMsg(e, "Could not add liability"));
    }
  }

  async function closeLiability(l: V4Liability) {
    setError(null);
    try {
      await api.put(`/api/v4/liabilities/${l.chain_id}`, {
        expected_version: l.version, kind: l.kind, outstanding_amount: l.outstanding_amount, as_of: l.as_of,
        monthly_payment: l.monthly_payment, rate_type: l.rate_type, annual_rate: l.annual_rate,
        next_reset_date: l.next_reset_date, maturity_date: l.maturity_date, status: "closed",
      });
      load(false);
    } catch (e) {
      setError(errMsg(e, "Could not close liability"));
    }
  }

  async function addPref() {
    setError(null);
    try {
      await api.post("/api/v4/preferences", pref);
      setPref({ ...pref, value: "", confirmed: false });
      load(false);
    } catch (e) {
      setError(errMsg(e, "Could not add restriction"));
    }
  }

  async function revoke(p: V4Preference) {
    try {
      await api.put(`/api/v4/preferences/${p.chain_id}`, { expected_version: p.version, status: "revoked" });
      load(false);
    } catch (e) {
      setError(errMsg(e, "Could not remove restriction"));
    }
  }

  if (!profile) {
    return error ? (
      <div role="alert" className="space-y-2">
        <h1 className="text-xl font-semibold text-text-primary">Financial profile</h1>
        <p className="text-sm text-negative">Could not load your financial profile: {error}</p>
        <Button size="sm" variant="secondary" onClick={() => { setError(null); load(true); }}>Try again</Button>
      </div>
    ) : (
      <div aria-busy="true" className="space-y-2">
        <h1 className="text-xl font-semibold text-text-primary">Financial profile</h1>
        <p className="text-sm text-text-muted">Loading your saved answers…</p>
      </div>
    );
  }
  const c = profile.capacity;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Financial profile</h1>
        <p className="text-sm text-text-muted">
          Facts only you can confirm. Leave a box empty if you do not know: it stays &quot;unknown&quot; and limits what the app
          may suggest. Nothing here is guessed from your holdings.
        </p>
      </div>
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}
      {msg && <p role="status" className="text-sm text-positive">{msg}</p>}

      <Card title="Your finances">
        <div className="grid gap-3 sm:grid-cols-2">
          {MONEY_FIELDS.map((m) => (
            <label key={m.key} className="text-sm text-text-primary">
              {m.label}
              <input className={INPUT} inputMode="decimal" value={form[m.key] ?? ""} onChange={(e) => setForm({ ...form, [m.key]: e.target.value })} />
              {m.hint && <span className="text-xs text-text-muted">{m.hint}</span>}
            </label>
          ))}
          <label className="text-sm text-text-primary">
            Income stability
            <select className={INPUT} value={form.income_stability ?? ""} onChange={(e) => setForm({ ...form, income_stability: e.target.value })}>
              <option value="">Unknown</option><option value="stable">Stable</option><option value="variable">Variable</option><option value="uncertain">Uncertain</option>
            </select>
          </label>
          <label className="text-sm text-text-primary">
            Dependents
            <input className={INPUT} inputMode="numeric" value={form.dependents ?? ""} onChange={(e) => setForm({ ...form, dependents: e.target.value })} />
          </label>
          <label className="text-sm text-text-primary">
            Investing experience
            <select className={INPUT} value={form.knowledge_level ?? ""} onChange={(e) => setForm({ ...form, knowledge_level: e.target.value })}>
              <option value="">Unknown</option><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option>
            </select>
          </label>
          <label className="text-sm text-text-primary">
            Your employer&apos;s stock, if you hold it (symbol or ISIN)
            <input className={INPUT} value={form.employer_exposure ?? ""} onChange={(e) => setForm({ ...form, employer_exposure: e.target.value })} />
          </label>
        </div>

        <h3 className="mt-5 text-sm font-medium text-text-primary">How you react to losses</h3>
        <div className="mt-2 grid gap-3 sm:grid-cols-3">
          {TOLERANCE_QUESTIONS.map((q) => (
            <label key={q.key} className="text-sm text-text-primary">
              {q.label}
              <select className={INPUT} value={form[q.key] ?? ""} onChange={(e) => setForm({ ...form, [q.key]: e.target.value })}>
                <option value="">Not answered</option>
                {q.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
          ))}
        </div>
        <div className="mt-4"><Button onClick={save} loading={busy}>Save financial profile</Button></div>
      </Card>

      <Card title="What this means (raw constraints, not a verdict)">
        <p className="text-sm text-text-muted">
          Risk tolerance (how you feel about losses):{" "}
          <strong className="text-text-primary">
            {profile.tolerance.status === "ready" ? `${profile.tolerance.band} (score ${profile.tolerance.score}), from your answers only` : `unknown, missing: ${profile.tolerance.missing.join(", ")}`}
          </strong>
        </p>
        <p className="mt-2 text-sm text-text-muted">
          Capacity (what you can afford to lose): <strong className="text-text-primary">{c.status === "capacity_unknown" ? `unknown, missing: ${c.missing.join(", ")}` : "inputs complete"}</strong>
        </p>
        <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-text-muted">Essential monthly outgo</dt>
            <dd>{rupees(c.monthly_essential_outgo)}</dd>
            {c.monthly_essential_outgo && profile.facts.monthly_essential_expenses !== null && (
              <dd className="text-xs text-text-muted">
                = expenses {rupees(profile.facts.monthly_essential_expenses)} + loan payments you recorded {rupees(String(Math.max(0, Number(c.monthly_essential_outgo) - Number(profile.facts.monthly_essential_expenses))))}
              </dd>
            )}
          </div>
          <div><dt className="text-xs text-text-muted">Reserve covers</dt><dd>{c.reserve_coverage_months ? `${c.reserve_coverage_months} months` : "unknown"} (target {rupees(c.reserve_target_amount)})</dd></div>
          <div><dt className="text-xs text-text-muted">Income left after essentials</dt><dd>{rupees(c.computed_monthly_surplus)}</dd></div>
          <div><dt className="text-xs text-text-muted">Loan payments / income</dt><dd>{c.debt_service_ratio ? `${(Number(c.debt_service_ratio) * 100).toFixed(1)}%` : "unknown"}</dd></div>
          <div><dt className="text-xs text-text-muted">Known obligations, next 12 months</dt><dd>{rupees(c.near_term_obligations_12m)}</dd></div>
        </dl>
        {c.stated_surplus_exceeds_computed && <p className="mt-2 text-sm text-warning">The amount you said you can invest is higher than income minus essentials. We use your figure only for what-ifs and flag the difference.</p>}
        {c.debt_payments_incomplete && <p className="mt-2 text-sm text-warning">Some loans have no monthly payment entered, so essential outgo may be understated.</p>}
        {c.binding_constraints.length > 0 ? (
          <ul className="mt-2 list-inside list-disc text-sm text-negative">
            {c.binding_constraints.map((b) => <li key={b.rule}>{b.rule.replace(/_/g, " ")}: {b.detail}</li>)}
          </ul>
        ) : null}
        <p className="mt-2 text-xs text-text-muted">
          {c.blocks_risk_increasing_actions ? "Suggestions that add risk are blocked until this is resolved." : "No blocking constraint found by the current (unreviewed) default rules."} Rules: {c.policy_version}.
        </p>
      </Card>

      {constraints && (
        <Card title="What limits how much risk new money may take">
          <p className={`text-sm font-medium ${constraints.risk_increasing_allowed ? "text-positive" : "text-negative"}`}>
            {constraints.risk_increasing_allowed ? "Nothing currently blocks suggestions that add risk." : "Suggestions that add risk are blocked for now."}
          </p>
          <ul className="mt-2 space-y-1 text-sm text-text-muted">
            {constraints.ceilings.map((c) => (
              <li key={c.source}>
                <strong className="text-text-primary">{c.source.replace("_", " ")}</strong>: {c.status}{c.band ? ` (${c.band})` : ""}{c.detail ? `, ${c.detail}` : ""}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-text-muted">{constraints.note} Rules: {constraints.policy_version}.</p>
        </Card>
      )}

      <Card title="Loans and other liabilities">
        {liabilities.length === 0 ? <p className="text-sm text-text-muted">None recorded.</p> : (
          <ul className="space-y-2 text-sm">
            {liabilities.map((l) => (
              <li key={l.chain_id} className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {l.kind.replace("_", " ")}: {rupees(l.outstanding_amount)} outstanding as of {l.as_of}
                  {l.monthly_payment ? `, ${rupees(l.monthly_payment)}/month` : ", payment unknown"}
                  {!l.rate_sensitivity_known && <span className="ml-2 text-xs text-warning">rate terms unknown</span>}
                </span>
                <Button size="sm" variant="secondary" onClick={() => closeLiability(l)}>Mark closed</Button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 grid gap-3 sm:grid-cols-5">
          <label className="text-sm">Type
            <select className={INPUT} value={liab.kind} onChange={(e) => setLiab({ ...liab, kind: e.target.value })}>
              {["home_loan", "personal_loan", "credit_card", "education_loan", "vehicle_loan", "other"].map((k) => <option key={k} value={k}>{k.replace("_", " ")}</option>)}
            </select>
          </label>
          <label className="text-sm">Outstanding (₹)<input className={INPUT} inputMode="decimal" value={liab.outstanding_amount} onChange={(e) => setLiab({ ...liab, outstanding_amount: e.target.value })} /></label>
          <label className="text-sm">Monthly payment (₹)<input className={INPUT} inputMode="decimal" value={liab.monthly_payment} onChange={(e) => setLiab({ ...liab, monthly_payment: e.target.value })} /></label>
          <label className="text-sm">Rate
            <select className={INPUT} value={liab.rate_type} onChange={(e) => setLiab({ ...liab, rate_type: e.target.value })}>
              <option value="unknown">Unknown</option><option value="fixed">Fixed</option><option value="floating">Floating</option>
            </select>
          </label>
          <label className="text-sm">Next rate reset<input type="date" className={INPUT} value={liab.next_reset_date} onChange={(e) => setLiab({ ...liab, next_reset_date: e.target.value })} /></label>
        </div>
        <div className="mt-3"><Button size="sm" variant="secondary" onClick={addLiability} disabled={!liab.outstanding_amount.trim()}>Add liability</Button></div>
      </Card>

      <Card title="Things you do not want to invest in">
        {prefs.length === 0 ? <p className="text-sm text-text-muted">No restrictions.</p> : (
          <ul className="space-y-1 text-sm">
            {prefs.map((p) => (
              <li key={p.chain_id} className="flex items-center justify-between gap-2">
                <span>{p.kind.replace("exclude_", "exclude ").replace("_", " ")}: {p.value}{p.expires_on ? ` (until ${p.expires_on})` : ""}</span>
                <Button size="sm" variant="secondary" onClick={() => revoke(p)}>Remove</Button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="text-sm">Type
            <select className={INPUT} value={pref.kind} onChange={(e) => setPref({ ...pref, kind: e.target.value })}>
              <option value="exclude_sector">Sector</option><option value="exclude_asset_type">Asset type</option><option value="exclude_isin">Specific ISIN</option>
            </select>
          </label>
          <label className="text-sm">Value<input className={INPUT} value={pref.value} onChange={(e) => setPref({ ...pref, value: e.target.value })} /></label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={pref.confirmed} onChange={(e) => setPref({ ...pref, confirmed: e.target.checked })} /> I confirm this restriction</label>
          <Button size="sm" variant="secondary" onClick={addPref} disabled={!pref.value.trim() || !pref.confirmed}>Add</Button>
        </div>
      </Card>
    </div>
  );
}
