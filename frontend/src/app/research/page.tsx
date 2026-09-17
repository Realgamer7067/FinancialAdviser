"use client";

import { FormEvent, useState } from "react";
import { motion } from "framer-motion";
import clsx from "clsx";
import { FlaskConical } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ResearchBranchStatus, ResearchSessionOut } from "@/lib/types";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";

const INPUT =
  "mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

const BRANCHES = [
  { key: "financials_valuation", label: "Financials & valuation" },
  { key: "events_governance", label: "Events & governance" },
  { key: "peers_downside", label: "Peers & downside" },
] as const;

// Public, stable, text-heavy pages -- stand-ins for a real search tool,
// which V3 9.3 hasn't built yet. This is the only place these URLs are used.
const EXAMPLE_URLS: Record<string, string[]> = {
  financials_valuation: ["https://en.wikipedia.org/wiki/Reliance_Industries"],
  events_governance: ["https://en.wikipedia.org/wiki/Tata_Consultancy_Services"],
  peers_downside: ["https://en.wikipedia.org/wiki/HDFC_Bank"],
};

const BRANCH_STATUS_STYLE: Record<ResearchBranchStatus, string> = {
  complete: "bg-positive/10 text-positive",
  partial: "bg-amber-500/10 text-amber-600",
  unavailable: "bg-negative/10 text-negative",
  failed: "bg-negative/10 text-negative",
  cancelled: "bg-text-muted/10 text-text-muted",
  pending: "bg-text-muted/10 text-text-muted",
  running: "bg-accent/10 text-accent",
};

function BranchBadge({ status }: { status: ResearchBranchStatus }) {
  return (
    <span className={clsx("rounded-full px-2.5 py-1 text-xs font-medium capitalize", BRANCH_STATUS_STYLE[status])}>
      {status}
    </span>
  );
}

function parseUrls(text: string): string[] {
  return text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

function VerificationStats({ v }: { v: NonNullable<ResearchSessionOut["verification"]> }) {
  const stats: { label: string; value: number; colorClass: string }[] = [
    { label: "Supported", value: v.supported_count, colorClass: "text-positive" },
    { label: "Unsupported", value: v.unsupported_count, colorClass: "text-negative" },
    { label: "Unknown", value: v.unknown_count, colorClass: "text-text-muted" },
    { label: "Contradicted", value: v.contradicted_count, colorClass: "text-negative" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map((s) => (
        <div key={s.label} className="rounded-md border border-border bg-bg px-3 py-2 text-center">
          <p className={clsx("text-lg font-semibold", s.colorClass)}>{s.value}</p>
          <p className="text-xs text-text-muted">{s.label}</p>
        </div>
      ))}
    </div>
  );
}

function ClaimList({ items }: { items: import("@/lib/types").ClaimReference[] }) {
  if (items.length === 0) return <p className="text-sm text-text-muted">None cited.</p>;
  return (
    <ul className="space-y-1.5">
      {items.map((c) => (
        <li key={c.fact_id} className="flex items-start gap-2 text-sm">
          <span
            className={clsx(
              "mt-0.5 shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium capitalize",
              c.support_status === "supported" ? "bg-positive/10 text-positive" : "bg-text-muted/10 text-text-muted"
            )}
          >
            {c.support_status}
          </span>
          <span className="text-text-primary">{c.text}</span>
        </li>
      ))}
    </ul>
  );
}

function ReportView({ report }: { report: NonNullable<ResearchSessionOut["report"]> }) {
  return (
    <Card title={`Report: ${report.entity}`}>
      <div className="space-y-4">
        <p className="text-sm text-text-primary">{report.short_assessment}</p>
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase text-text-muted">Business</h3>
          <p className="text-sm text-text-primary">{report.business_explanation}</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase text-text-muted">Strongest supporting evidence</h3>
            <ClaimList items={report.strongest_supporting_evidence} />
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase text-text-muted">Strongest opposing evidence</h3>
            <ClaimList items={report.strongest_opposing_evidence} />
          </div>
        </div>
        {report.financial_context.length > 0 && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase text-text-muted">Financial context</h3>
            <ClaimList items={report.financial_context} />
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          {[
            ["Risks", report.risks],
            ["Catalysts", report.catalysts],
            ["Missing facts", report.missing_facts],
            ["Would change assessment if...", report.conditions_that_would_change_assessment],
          ].map(([label, items]) =>
            (items as string[]).length > 0 ? (
              <div key={label as string}>
                <h3 className="mb-1 text-xs font-semibold uppercase text-text-muted">{label}</h3>
                <ul className="list-inside list-disc space-y-0.5 text-sm text-text-primary">
                  {(items as string[]).map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            ) : null
          )}
        </div>
        <p className="text-xs text-text-muted">
          No target price or confidence number appears anywhere in this report by design -- see the platform&apos;s own
          "never guess" principle. Generated {new Date(report.generated_at).toLocaleString("en-IN")}.
        </p>
      </div>
    </Card>
  );
}

function ResultView({ session }: { session: ResearchSessionOut }) {
  return (
    <motion.div variants={fadeInUp} className="space-y-4">
      <Card title="Session">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-sm text-text-primary">{session.question}</p>
            <p className="mt-1 text-xs text-text-muted">Session ID: {session.id}</p>
          </div>
          <span className="rounded-full bg-accent/10 px-3 py-1 text-xs font-medium capitalize text-accent">
            {session.state.replaceAll("_", " ")}
          </span>
        </div>

        {session.state === "ready_to_publish" && session.synthesis_error && (
          <p className="mt-3 rounded-md border border-dashed border-border bg-bg px-3 py-2 text-xs text-text-muted">
            Retrieval and verification are complete, but this session has <strong>not</strong> been synthesized into a
            report: {session.synthesis_error} -- what you see below is the raw evidence state, not a finished report.
          </p>
        )}

        {session.stopped_reason && (
          <p className="mt-3 rounded-md border border-border bg-bg px-3 py-2 text-xs text-text-muted">
            Stopped early: {session.stopped_reason}
          </p>
        )}
      </Card>

      {session.report && <ReportView report={session.report} />}

      <Card title="Branches">
        <div className="space-y-2">
          {session.branches.map((b) => (
            <div key={b.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-3 py-2">
              <div>
                <p className="text-sm font-medium text-text-primary">{b.branch_type.replaceAll("_", " ")}</p>
                {b.gap_reason && <p className="mt-0.5 text-xs text-text-muted">{b.gap_reason}</p>}
                {!b.gap_reason && <p className="mt-0.5 text-xs text-text-muted">{b.fact_ids.length} fact(s) retrieved</p>}
              </div>
              <BranchBadge status={b.status} />
            </div>
          ))}
        </div>
      </Card>

      <Card title="Named gaps">
        {session.named_gaps.length === 0 ? (
          <p className="text-sm text-text-muted">No gaps recorded -- every branch produced usable evidence.</p>
        ) : (
          <ul className="list-inside list-disc space-y-1 text-sm text-text-primary">
            {session.named_gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Claim verification">
        {session.verification ? (
          <VerificationStats v={session.verification} />
        ) : (
          <p className="text-sm text-text-muted">
            Not available -- verification tallies are computed once, during the run, and are not persisted; re-fetching
            an existing session (e.g. via its permalink) can only show branch status and named gaps, not this summary.
          </p>
        )}
      </Card>
    </motion.div>
  );
}

export default function ResearchPage() {
  const [question, setQuestion] = useState("");
  const [urlText, setUrlText] = useState<Record<string, string>>({
    financials_valuation: "",
    events_governance: "",
    peers_downside: "",
  });
  const [findSources, setFindSources] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<ResearchSessionOut | null>(null);

  async function runSession(q: string, branchFetchUrls: Record<string, string[]>, findSourcesOverride?: boolean) {
    setLoading(true);
    setError(null);
    setSession(null);
    try {
      const res = await api.post<ResearchSessionOut>("/api/research/sessions", {
        question: q,
        instrument_ids: [],
        branch_fetch_urls: branchFetchUrls,
        find_sources: findSourcesOverride ?? findSources,
        budget_envelope: { max_fetches: 10 },
        cutoff_policy: {},
      });
      setSession(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to run research session");
    } finally {
      setLoading(false);
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    const branchFetchUrls: Record<string, string[]> = {};
    for (const b of BRANCHES) branchFetchUrls[b.key] = parseUrls(urlText[b.key]);
    const totalUrls = Object.values(branchFetchUrls).reduce((n, urls) => n + urls.length, 0);
    if (totalUrls === 0 && !findSources) {
      // With search off, a branch with no URLs and no auto-discovery has
      // nothing to fetch -- catch that before wasting the round-trip.
      // With search on, empty branches are expected: Gemini search
      // grounding supplies the URLs instead.
      setError('Add at least one URL below, or turn on "Find sources automatically", or use "Run example research".');
      return;
    }
    await runSession(question, branchFetchUrls);
  }

  async function onRunExample() {
    setQuestion("How is Example Bank Ltd performing?");
    await runSession("How is Example Bank Ltd performing?", EXAMPLE_URLS, false);
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.div variants={fadeInUp}>
        <h1 className="text-xl font-semibold text-text-primary">Research</h1>
        <p className="mt-1 text-sm text-text-muted">
          Runs real retrieval, claim verification, and (once evidence verifies) a synthesized written report against
          evidence found for your question. Sources come from URLs you paste in, or are found automatically via
          Gemini search.
        </p>
      </motion.div>

      <motion.div variants={fadeInUp}>
        <Card title="Start a research session">
          <form onSubmit={onSubmit} className="space-y-4">
            <label className="block text-sm text-text-primary">
              Question
              <input
                type="text"
                required
                placeholder="e.g. How is Example Bank Ltd performing?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                className={INPUT}
              />
            </label>

            <label className="flex cursor-pointer items-center gap-2 text-sm text-text-primary">
              <input
                type="checkbox"
                checked={findSources}
                onChange={(e) => setFindSources(e.target.checked)}
                className="accent-accent"
              />
              Find sources automatically (Gemini search) for any branch left empty below
            </label>
            {findSources && (
              <p className="rounded-md border border-dashed border-border bg-bg px-3 py-2 text-xs text-text-muted">
                Search grounding currently sits behind a separate, stricter quota than the rest of this app&apos;s
                Gemini calls -- if it&apos;s exhausted, an empty branch just falls back to "no sources found," same as
                before search existed. Paste URLs below any time to bypass it entirely.
              </p>
            )}

            <div className="grid gap-3 sm:grid-cols-3">
              {BRANCHES.map((b) => (
                <label key={b.key} className="block text-sm text-text-primary">
                  {b.label} URLs {findSources && <span className="font-normal text-text-muted">(optional -- auto-search fills gaps)</span>}
                  <textarea
                    rows={3}
                    placeholder={"One URL per line"}
                    value={urlText[b.key]}
                    onChange={(e) => setUrlText((prev) => ({ ...prev, [b.key]: e.target.value }))}
                    className={clsx(INPUT, "resize-y font-mono text-xs")}
                  />
                </label>
              ))}
            </div>

            <div className="flex flex-wrap gap-3">
              <Button type="submit" disabled={loading} loading={loading}>
                {loading ? "Running..." : "Run research"}
              </Button>
              <Button type="button" variant="secondary" disabled={loading} onClick={onRunExample}>
                Run example research
              </Button>
            </div>
          </form>

          {error && <p className="mt-3 text-sm text-negative">{error}</p>}
        </Card>
      </motion.div>

      {session ? (
        <ResultView session={session} />
      ) : (
        !loading &&
        !error && (
          <motion.div variants={fadeInUp}>
            <EmptyState
              icon={FlaskConical}
              title="No research session yet"
              message="Start one above, or run the example, to see retrieval status, named gaps, and claim verification."
            />
          </motion.div>
        )
      )}
    </motion.div>
  );
}
