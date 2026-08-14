"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { RiskProfile } from "@/lib/types";

const RADIO_GROUP = "block space-y-1 text-sm";

export default function OnboardingPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RiskProfile | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const form = new FormData(e.currentTarget);
    const payload = {
      age: Number(form.get("age")),
      employment_status: String(form.get("employment_status")),
      monthly_income_range: String(form.get("monthly_income_range")),
      monthly_investable_amount: Number(form.get("monthly_investable_amount")),
      total_initial_investment: Number(form.get("total_initial_investment")),
      existing_investments: {},
      existing_debt: Number(form.get("existing_debt") || 0),
      emergency_fund_status: String(form.get("emergency_fund_status")),
      dependents: Number(form.get("dependents") || 0),
      investment_objective: String(form.get("investment_objective")),
      investment_horizon_years: Number(form.get("investment_horizon_years")),
      liquidity_requirement: String(form.get("liquidity_requirement")),
      investment_frequency: String(form.get("investment_frequency")),
      raw_risk_answers: {
        portfolio_drop_20pct_reaction: String(form.get("portfolio_drop_20pct_reaction")),
        priority: String(form.get("priority")),
        loss_tolerance: String(form.get("loss_tolerance")),
      },
    };

    try {
      const risk = await api.post<RiskProfile>("/api/onboarding", payload);
      setResult(risk);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  if (result) {
    return (
      <div className="mx-auto max-w-md space-y-4 rounded border bg-white p-6">
        <h1 className="text-lg font-semibold">Your investor profile is ready</h1>
        <p className="text-sm text-slate-600">
          Risk profile: <strong className="capitalize">{result.risk_profile}</strong> (score {result.risk_score}/100)
        </p>
        <p className="text-sm text-slate-600">Horizon: {result.investment_horizon_years} years</p>
        <button
          onClick={() => router.push("/dashboard")}
          className="w-full rounded bg-brand-600 px-4 py-2 text-white hover:bg-brand-700"
        >
          Go to dashboard
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="mx-auto max-w-xl space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Tell us about your finances</h1>
        <p className="text-sm text-slate-500">No jargon, just forms -- this builds your investor profile.</p>
      </div>

      <fieldset className="space-y-3 rounded border bg-white p-4">
        <legend className="px-1 text-sm font-medium">Personal & financial profile</legend>
        <label className={RADIO_GROUP}>
          Age
          <input name="age" type="number" min={18} max={100} required className="w-full rounded border px-3 py-2" />
        </label>
        <label className={RADIO_GROUP}>
          Employment status
          <select name="employment_status" required className="w-full rounded border px-3 py-2">
            <option value="salaried">Salaried</option>
            <option value="self_employed">Self-employed</option>
            <option value="business_owner">Business owner</option>
            <option value="student">Student</option>
            <option value="retired">Retired</option>
          </select>
        </label>
        <label className={RADIO_GROUP}>
          Monthly income range
          <select name="monthly_income_range" required className="w-full rounded border px-3 py-2">
            <option value="lt_25k">Below ₹25,000</option>
            <option value="25k_50k">₹25,000 - ₹50,000</option>
            <option value="50k_100k">₹50,000 - ₹1,00,000</option>
            <option value="100k_plus">Above ₹1,00,000</option>
          </select>
        </label>
        <label className={RADIO_GROUP}>
          Monthly amount you can invest (₹)
          <input name="monthly_investable_amount" type="number" min={0} required className="w-full rounded border px-3 py-2" />
        </label>
        <label className={RADIO_GROUP}>
          Total amount you want to invest now (₹)
          <input name="total_initial_investment" type="number" min={0} required className="w-full rounded border px-3 py-2" />
        </label>
        <label className={RADIO_GROUP}>
          Existing debt (₹, 0 if none)
          <input name="existing_debt" type="number" min={0} defaultValue={0} className="w-full rounded border px-3 py-2" />
        </label>
        <label className={RADIO_GROUP}>
          Emergency fund status
          <select name="emergency_fund_status" required className="w-full rounded border px-3 py-2">
            <option value="none">No emergency fund yet</option>
            <option value="partial">Have some, not 3-6 months of expenses</option>
            <option value="full">3-6+ months of expenses saved</option>
          </select>
        </label>
        <label className={RADIO_GROUP}>
          Dependents
          <input name="dependents" type="number" min={0} defaultValue={0} className="w-full rounded border px-3 py-2" />
        </label>
        <label className={RADIO_GROUP}>
          Investment objective
          <select name="investment_objective" required className="w-full rounded border px-3 py-2">
            <option value="wealth_building">Long-term wealth building</option>
            <option value="retirement">Retirement</option>
            <option value="short_term_goal">A specific short-term goal</option>
            <option value="income">Regular income</option>
          </select>
        </label>
        <label className={RADIO_GROUP}>
          Investment horizon (years)
          <input name="investment_horizon_years" type="number" min={1} max={40} required className="w-full rounded border px-3 py-2" />
        </label>
        <label className={RADIO_GROUP}>
          Liquidity requirement
          <select name="liquidity_requirement" required className="w-full rounded border px-3 py-2">
            <option value="low">Low -- I won't need this money soon</option>
            <option value="medium">Medium -- might need some within a couple of years</option>
            <option value="high">High -- may need to withdraw soon</option>
          </select>
        </label>
        <label className={RADIO_GROUP}>
          How often will you invest?
          <select name="investment_frequency" required className="w-full rounded border px-3 py-2">
            <option value="monthly">Monthly (SIP-style)</option>
            <option value="lump_sum">One-time lump sum</option>
            <option value="irregular">Irregular</option>
          </select>
        </label>
      </fieldset>

      <fieldset className="space-y-4 rounded border bg-white p-4">
        <legend className="px-1 text-sm font-medium">Risk profile</legend>

        <div>
          <p className="mb-1 text-sm font-medium">What would you do if your portfolio fell 20%?</p>
          {[
            ["sell_all", "Sell everything"],
            ["sell_some", "Sell some"],
            ["hold", "Hold"],
            ["buy_more", "Buy more"],
          ].map(([value, label]) => (
            <label key={value} className="flex items-center gap-2 text-sm">
              <input type="radio" name="portfolio_drop_20pct_reaction" value={value} required /> {label}
            </label>
          ))}
        </div>

        <div>
          <p className="mb-1 text-sm font-medium">What matters most to you?</p>
          {[
            ["capital_preservation", "Capital preservation"],
            ["balanced_growth", "Balanced growth"],
            ["maximum_growth", "Maximum long-term growth"],
          ].map(([value, label]) => (
            <label key={value} className="flex items-center gap-2 text-sm">
              <input type="radio" name="priority" value={value} required /> {label}
            </label>
          ))}
        </div>

        <div>
          <p className="mb-1 text-sm font-medium">How much temporary loss are you comfortable with?</p>
          {[
            ["0_10", "0-10%"],
            ["10_20", "10-20%"],
            ["20_30", "20-30%"],
            ["30_50", "30-50%"],
            ["50_plus", "50%+"],
          ].map(([value, label]) => (
            <label key={value} className="flex items-center gap-2 text-sm">
              <input type="radio" name="loss_tolerance" value={value} required /> {label}
            </label>
          ))}
        </div>
      </fieldset>

      {error && <p className="text-sm text-red-600">{error}</p>}
      <button
        disabled={loading}
        className="w-full rounded bg-brand-600 px-4 py-2 text-white hover:bg-brand-700 disabled:opacity-50"
      >
        {loading ? "Computing your risk profile..." : "Submit"}
      </button>
    </form>
  );
}
