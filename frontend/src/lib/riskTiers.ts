export type RiskTier = "safer" | "moderate" | "risky" | "riskiest";

export const RISK_TIER_ORDER: RiskTier[] = ["safer", "moderate", "risky", "riskiest"];

// Which of the stock's own risk tiers reasonably fit each user risk-tolerance
// profile -- a static lookup, same spirit as the ladders already duplicated
// between app/risk/scoring.py and app/scoring/subscores.py on the backend.
const FITS_PROFILE: Record<string, RiskTier[]> = {
  conservative: ["safer"],
  moderate: ["safer", "moderate", "risky"],
  aggressive: ["moderate", "risky", "riskiest"],
};

export function tierFitsProfile(tier: RiskTier | null, userRiskProfile: string | null): boolean {
  if (tier === null || userRiskProfile === null) return false;
  return FITS_PROFILE[userRiskProfile]?.includes(tier) ?? false;
}
