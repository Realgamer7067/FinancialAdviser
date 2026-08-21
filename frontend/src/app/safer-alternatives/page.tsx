"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { RiskProfile, SaferAlternativesOut } from "@/lib/types";
import Card from "@/components/ui/Card";

function SaferAlternativesInner() {
  const [data, setData] = useState<SaferAlternativesOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [userRiskProfile, setUserRiskProfile] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<SaferAlternativesOut>("/api/education/safer-alternatives")
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load content"));
    api
      .get<RiskProfile>("/api/onboarding/me")
      .then((p) => setUserRiskProfile(p.risk_profile))
      .catch(() => setUserRiskProfile(null));
  }, []);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return <p className="text-sm text-slate-500">Loading...</p>;

  const items = [...data.items].sort((a, b) => {
    const aFits = userRiskProfile !== null && a.suited_risk_profiles.includes(userRiskProfile);
    const bFits = userRiskProfile !== null && b.suited_risk_profiles.includes(userRiskProfile);
    return aFits === bFits ? 0 : aFits ? -1 : 1;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Safer Alternatives</h1>
        <p className="text-sm text-slate-500">
          Lower-volatility ways to hold money alongside equities -- general education, not a live quote.
        </p>
      </div>

      <div className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{data.disclaimer}</div>

      <div className="grid gap-4 sm:grid-cols-2">
        {items.map((item) => {
          const fits = userRiskProfile !== null && item.suited_risk_profiles.includes(userRiskProfile);
          return (
            <Card key={item.key} className={fits ? "border-brand-600" : ""}>
              <div className="flex items-start justify-between gap-2">
                <h2 className="font-medium">{item.name}</h2>
                {fits && (
                  <span className="shrink-0 rounded-full bg-brand-100 px-2 py-1 text-xs font-medium text-brand-800">
                    Matches your risk profile
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm text-slate-600">{item.description}</p>
              <dl className="mt-3 space-y-1 text-sm">
                <div className="flex justify-between gap-2">
                  <dt className="shrink-0 text-slate-500">Indicative return</dt>
                  <dd className="text-right">{item.indicative_return_range}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="shrink-0 text-slate-500">Liquidity</dt>
                  <dd className="text-right">{item.liquidity}</dd>
                </div>
                {item.typical_lock_in && (
                  <div className="flex justify-between gap-2">
                    <dt className="shrink-0 text-slate-500">Typical lock-in</dt>
                    <dd className="text-right">{item.typical_lock_in}</dd>
                  </div>
                )}
              </dl>
              <p className="mt-2 text-xs text-slate-500">{item.risk_note}</p>
              {item.eligibility_note && <p className="mt-1 text-xs text-slate-400">{item.eligibility_note}</p>}
            </Card>
          );
        })}
      </div>
    </div>
  );
}

export default function SaferAlternativesPage() {
  return <SaferAlternativesInner />;
}
