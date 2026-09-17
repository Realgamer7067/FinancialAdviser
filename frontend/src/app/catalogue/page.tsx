"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";
import { useState } from "react";
import { FlaskConical, Library } from "lucide-react";
import type { ProductCatalogEntryOut, ProductType, SupportLevel } from "@/lib/types";
import { useApiData } from "@/lib/useApiData";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonCard } from "@/components/ui/Skeleton";

function formatRupees(v: string | null): string {
  if (v === null) return "-";
  const n = Number(v);
  if (Number.isNaN(n)) return "-";
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

const PRODUCT_TYPES: ProductType[] = [
  "direct_listed_equity",
  "equity_index_fund",
  "equity_index_etf",
  "bank_fd",
  "bank_rd",
  "treasury_bill",
  "govt_security",
  "liquid_debt_fund",
  "gold_fund_etf",
  "locked_account",
  "hybrid_fund",
  "other",
];

const SUPPORT_LEVELS: SupportLevel[] = ["education_only", "holdings_only", "category_planning", "instrument_planning"];

function labelize(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const SUPPORT_LEVEL_STYLE: Record<string, string> = {
  education_only: "bg-border/60 text-text-muted",
  holdings_only: "bg-accent-subtle text-accent",
  category_planning: "bg-accent-subtle text-accent",
  instrument_planning: "bg-positive/15 text-positive",
};

function CatalogueInner() {
  const [productType, setProductType] = useState<string>("");
  const [supportLevel, setSupportLevel] = useState<string>("");

  const path = useMemo(() => {
    const params = new URLSearchParams();
    if (productType) params.set("product_type", productType);
    if (supportLevel) params.set("support_level", supportLevel);
    const qs = params.toString();
    return `/api/catalogue${qs ? `?${qs}` : ""}`;
  }, [productType, supportLevel]);

  const { data: entries, error } = useApiData<ProductCatalogEntryOut[]>(path);

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.div variants={fadeInUp}>
        <h1 className="text-xl font-semibold text-text-primary">Product Catalogue</h1>
        <p className="text-sm text-text-muted">
          Products this platform knows terms for. Some entries are synthetic fixtures used while real sourced
          catalogue data is pending -- they are always badged below and must never be treated as real market
          terms.
        </p>
      </motion.div>

      <motion.div variants={fadeInUp} className="flex flex-wrap gap-3">
        <label className="text-sm text-text-primary">
          Product type
          <select
            value={productType}
            onChange={(e) => setProductType(e.target.value)}
            className="mt-1 block rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <option value="">All</option>
            {PRODUCT_TYPES.map((t) => (
              <option key={t} value={t}>
                {labelize(t)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-text-primary">
          Support level
          <select
            value={supportLevel}
            onChange={(e) => setSupportLevel(e.target.value)}
            className="mt-1 block rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <option value="">All</option>
            {SUPPORT_LEVELS.map((s) => (
              <option key={s} value={s}>
                {labelize(s)}
              </option>
            ))}
          </select>
        </label>
      </motion.div>

      {error && <p className="text-sm text-negative">{error}</p>}

      {!entries && !error && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {entries && entries.length === 0 && (
        <motion.div variants={fadeInUp}>
          <EmptyState icon={Library} title="No catalogue entries match" message="Try clearing the filters." />
        </motion.div>
      )}

      {entries && entries.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {entries.map((e) => (
            <motion.div key={e.id} variants={fadeInUp}>
              <Card>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h2 className="font-medium text-text-primary">{e.issuer_or_amc}</h2>
                    <p className="text-xs text-text-muted">{labelize(e.product_type)}</p>
                  </div>
                  {e.is_synthetic && (
                    <span className="flex shrink-0 items-center gap-1 rounded-full bg-warning-subtle px-2 py-1 text-xs font-medium text-warning">
                      <FlaskConical className="h-3 w-3" /> Synthetic
                    </span>
                  )}
                </div>

                <div className="mt-2">
                  <span
                    className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                      SUPPORT_LEVEL_STYLE[e.resolved_support_level] ?? "bg-border/60 text-text-muted"
                    }`}
                  >
                    {labelize(e.resolved_support_level)}
                  </span>
                </div>

                <dl className="mt-3 space-y-1 text-sm">
                  <div className="flex justify-between gap-2">
                    <dt className="shrink-0 text-text-muted">Valuation method</dt>
                    <dd className="text-right text-text-primary">{labelize(e.valuation_method)}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="shrink-0 text-text-muted">Minimum initial</dt>
                    <dd className="text-right text-text-primary">{formatRupees(e.minimum_initial)}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="shrink-0 text-text-muted">Minimum additional</dt>
                    <dd className="text-right text-text-primary">{formatRupees(e.minimum_additional)}</dd>
                  </div>
                  {e.maturity_or_lock_rule && (
                    <div className="flex justify-between gap-2">
                      <dt className="shrink-0 text-text-muted">Lock-in / maturity</dt>
                      <dd className="text-right text-text-primary">{e.maturity_or_lock_rule}</dd>
                    </div>
                  )}
                  <div className="flex justify-between gap-2">
                    <dt className="shrink-0 text-text-muted">Contribution methods</dt>
                    <dd className="text-right text-text-primary">{e.eligible_contribution_methods.join(", ") || "-"}</dd>
                  </div>
                </dl>

                <p className="mt-2 text-xs text-text-muted">
                  {e.is_synthetic
                    ? "Fixture data -- not a real quoted product, for planning-flow demonstration only."
                    : `Terms as of ${e.source_freshness}.`}
                </p>
              </Card>
            </motion.div>
          ))}
        </div>
      )}
    </motion.div>
  );
}

export default function CataloguePage() {
  return <CatalogueInner />;
}
