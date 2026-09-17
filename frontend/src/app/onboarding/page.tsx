"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { api, ApiError } from "@/lib/api";
import type { RiskProfile } from "@/lib/types";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import RiskGauge from "@/components/ui/RiskGauge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";

const LABEL = "block space-y-1 text-sm text-text-primary";
const INPUT =
  "w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

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
      <motion.div initial="hidden" animate="visible" variants={fadeInUp} className="mx-auto max-w-md">
        <Card className="space-y-4">
          <h1 className="text-lg font-semibold text-text-primary">Your investor profile is ready</h1>
          <RiskGauge value={result.risk_score} label={result.risk_profile} />
          <p className="text-sm text-text-muted">Horizon: {result.investment_horizon_years} years</p>
          <Button onClick={() => router.push("/dashboard")} className="w-full">
            Go to dashboard
          </Button>
        </Card>
      </motion.div>
    );
  }

  return (
    <motion.form
      onSubmit={onSubmit}
      initial="hidden"
      animate="visible"
      variants={staggerChildren}
      className="mx-auto max-w-xl space-y-8"
    >
      <motion.div variants={fadeInUp}>
        <h1 className="text-xl font-semibold text-text-primary">Tell us about your finances</h1>
        <p className="text-sm text-text-muted">No jargon, just forms — this builds your investor profile.</p>
      </motion.div>

      <motion.fieldset variants={fadeInUp} className="space-y-3 rounded-lg border border-border bg-surface p-4 shadow-sm">
        <legend className="px-1 text-sm font-medium text-text-primary">Personal & financial profile</legend>
        <label className={LABEL}>
          Age
          <input name="age" type="number" min={18} max={100} required className={INPUT} />
        </label>
        <label className={LABEL}>
          Employment status
          <select name="employment_status" required className={INPUT}>
            <option value="salaried">Salaried</option>
            <option value="self_employed">Self-employed</option>
            <option value="business_owner">Business owner</option>
            <option value="student">Student</option>
            <option value="retired">Retired</option>
          </select>
        </label>
        <label className={LABEL}>
          Monthly income range
          <select name="monthly_income_range" required className={INPUT}>
            <option value="lt_25k">Below ₹25,000</option>
            <option value="25k_50k">₹25,000 - ₹50,000</option>
            <option value="50k_100k">₹50,000 - ₹1,00,000</option>
            <option value="100k_plus">Above ₹1,00,000</option>
          </select>
        </label>
        <label className={LABEL}>
          Monthly amount you can invest (₹)
          <input name="monthly_investable_amount" type="number" min={0} required className={INPUT} />
        </label>
        <label className={LABEL}>
          Total amount you want to invest now (₹)
          <input name="total_initial_investment" type="number" min={0} required className={INPUT} />
        </label>
        <label className={LABEL}>
          Existing debt (₹, 0 if none)
          <input name="existing_debt" type="number" min={0} defaultValue={0} className={INPUT} />
        </label>
        <label className={LABEL}>
          Emergency fund status
          <select name="emergency_fund_status" required className={INPUT}>
            <option value="none">No emergency fund yet</option>
            <option value="partial">Have some, not 3-6 months of expenses</option>
            <option value="full">3-6+ months of expenses saved</option>
          </select>
        </label>
        <label className={LABEL}>
          Dependents
          <input name="dependents" type="number" min={0} defaultValue={0} className={INPUT} />
        </label>
        <label className={LABEL}>
          Investment objective
          <select name="investment_objective" required className={INPUT}>
            <option value="wealth_building">Long-term wealth building</option>
            <option value="retirement">Retirement</option>
            <option value="short_term_goal">A specific short-term goal</option>
            <option value="income">Regular income</option>
          </select>
        </label>
        <label className={LABEL}>
          Investment horizon (years)
          <input name="investment_horizon_years" type="number" min={1} max={40} required className={INPUT} />
        </label>
        <label className={LABEL}>
          Liquidity requirement
          <select name="liquidity_requirement" required className={INPUT}>
            <option value="low">Low — I won&apos;t need this money soon</option>
            <option value="medium">Medium — might need some within a couple of years</option>
            <option value="high">High — may need to withdraw soon</option>
          </select>
        </label>
        <label className={LABEL}>
          How often will you invest?
          <select name="investment_frequency" required className={INPUT}>
            <option value="monthly">Monthly (SIP-style)</option>
            <option value="lump_sum">One-time lump sum</option>
            <option value="irregular">Irregular</option>
          </select>
        </label>
      </motion.fieldset>

      <motion.fieldset variants={fadeInUp} className="space-y-4 rounded-lg border border-border bg-surface p-4 shadow-sm">
        <legend className="px-1 text-sm font-medium text-text-primary">Risk profile</legend>

        <div>
          <p className="mb-1 text-sm font-medium text-text-primary">What would you do if your portfolio fell 20%?</p>
          {[
            ["sell_all", "Sell everything"],
            ["sell_some", "Sell some"],
            ["hold", "Hold"],
            ["buy_more", "Buy more"],
          ].map(([value, label]) => (
            <label key={value} className="flex items-center gap-2 text-sm text-text-muted">
              <input type="radio" name="portfolio_drop_20pct_reaction" value={value} required className="accent-accent" /> {label}
            </label>
          ))}
        </div>

        <div>
          <p className="mb-1 text-sm font-medium text-text-primary">What matters most to you?</p>
          {[
            ["capital_preservation", "Capital preservation"],
            ["balanced_growth", "Balanced growth"],
            ["maximum_growth", "Maximum long-term growth"],
          ].map(([value, label]) => (
            <label key={value} className="flex items-center gap-2 text-sm text-text-muted">
              <input type="radio" name="priority" value={value} required className="accent-accent" /> {label}
            </label>
          ))}
        </div>

        <div>
          <p className="mb-1 text-sm font-medium text-text-primary">How much temporary loss are you comfortable with?</p>
          {[
            ["0_10", "0-10%"],
            ["10_20", "10-20%"],
            ["20_30", "20-30%"],
            ["30_50", "30-50%"],
            ["50_plus", "50%+"],
          ].map(([value, label]) => (
            <label key={value} className="flex items-center gap-2 text-sm text-text-muted">
              <input type="radio" name="loss_tolerance" value={value} required className="accent-accent" /> {label}
            </label>
          ))}
        </div>
      </motion.fieldset>

      {error && (
        <motion.p variants={fadeInUp} className="text-sm text-negative">
          {error}
        </motion.p>
      )}
      <motion.div variants={fadeInUp}>
        <Button disabled={loading} loading={loading} className="w-full">
          {loading ? "Computing your risk profile..." : "Submit"}
        </Button>
      </motion.div>
    </motion.form>
  );
}
