"use client";

import { motion } from "framer-motion";
import { AlertTriangle, Building2, LineChart as LineChartIcon, MessagesSquare, ShieldAlert, TrendingDown, TrendingUp } from "lucide-react";
import type { CouncilRole, CouncilRoleOutput } from "@/lib/types";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import EmptyState from "@/components/ui/EmptyState";
import Card from "@/components/ui/Card";

const ROLE_META: Record<Exclude<CouncilRole, "planner" | "judge">, { label: string; icon: typeof TrendingUp }> = {
  bull: { label: "Bull case", icon: TrendingUp },
  bear: { label: "Bear case", icon: TrendingDown },
  fundamental: { label: "Fundamental read", icon: Building2 },
  quant: { label: "Quant read", icon: LineChartIcon },
  risk: { label: "Risk assessment", icon: ShieldAlert },
};

function RoleCard({ output }: { output: CouncilRoleOutput }) {
  const meta = ROLE_META[output.role as keyof typeof ROLE_META];
  if (!meta) return null;
  const Icon = meta.icon;
  const c = output.content as Record<string, unknown>;
  const summary = typeof c.summary === "string" ? c.summary : "";

  let bullets: string[] = [];
  let tags: string[] = [];
  if (output.role === "bull") bullets = (c.supporting_points as string[]) ?? [];
  if (output.role === "bear") bullets = (c.concerns as string[]) ?? [];
  if (output.role === "risk") {
    bullets = (c.key_risks as string[]) ?? [];
    tags = c.suitability ? [c.suitability as string] : [];
  }
  if (output.role === "fundamental") tags = [c.business_quality, c.valuation].filter(Boolean) as string[];
  if (output.role === "quant") tags = [c.technical_read, c.forecast_read].filter(Boolean) as string[];

  return (
    <motion.div variants={fadeInUp}>
      <Card className="h-full">
        <div className="mb-2 flex items-center gap-2">
          <Icon className="h-4 w-4 text-accent" />
          <h4 className="font-medium text-text-primary">{meta.label}</h4>
        </div>
        {tags.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {tags.map((t) => (
              <span key={t} className="rounded-full bg-accent-subtle px-2 py-0.5 text-xs font-medium capitalize text-accent">
                {t}
              </span>
            ))}
          </div>
        )}
        <p className="text-sm text-text-muted">{summary}</p>
        {bullets.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-text-muted">
            {bullets.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        )}
      </Card>
    </motion.div>
  );
}

function JudgeCallout({ output }: { output: CouncilRoleOutput }) {
  const c = output.content as {
    rationale?: string;
    contradictory_evidence?: string[];
    model_disagreements?: string[];
    missing_data?: string[];
  };
  const hasDisagreement = (c.contradictory_evidence?.length ?? 0) > 0 || (c.model_disagreements?.length ?? 0) > 0;

  return (
    <motion.div variants={fadeInUp}>
      <Card className="border-accent/30 bg-accent-subtle/40">
        <div className="mb-2 flex items-center gap-2">
          <MessagesSquare className="h-4 w-4 text-accent" />
          <h4 className="font-medium text-text-primary">Judge's verdict</h4>
        </div>
        {c.rationale && <p className="text-sm text-text-muted">{c.rationale}</p>}
        {hasDisagreement && (
          <div className="mt-3 flex items-start gap-2 rounded-md bg-warning-subtle p-2.5 text-sm text-warning">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              {[...(c.contradictory_evidence ?? []), ...(c.model_disagreements ?? [])].map((d, i) => (
                <p key={i}>{d}</p>
              ))}
            </div>
          </div>
        )}
        {(c.missing_data?.length ?? 0) > 0 && (
          <p className="mt-2 text-xs text-text-muted">Missing data: {c.missing_data!.join("; ")}</p>
        )}
      </Card>
    </motion.div>
  );
}

export default function CouncilTranscript({ outputs }: { outputs: CouncilRoleOutput[] }) {
  if (outputs.length === 0) {
    return (
      <EmptyState
        icon={MessagesSquare}
        title="Council reasoning not available"
        message="This run's analyst council (bull/bear/fundamental/quant/risk + judge) requires a configured LLM provider. The deterministic score and risk gate above were still computed and applied without it."
      />
    );
  }

  const judge = outputs.find((o) => o.role === "judge");
  const analysts = outputs.filter((o) => o.role !== "judge");

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        {analysts.map((o) => (
          <RoleCard key={o.role} output={o} />
        ))}
      </div>
      {judge && <JudgeCallout output={judge} />}
    </motion.div>
  );
}
