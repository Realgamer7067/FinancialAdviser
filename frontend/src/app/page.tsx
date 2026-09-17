"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { AlertTriangle, ShieldCheck, TrendingUp, XCircle } from "lucide-react";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import { fadeInUp, staggerChildren } from "@/lib/motion";

const FEATURES = [
  { title: "Evidence, not vibes", body: "Every recommendation cites the fundamentals, technicals, forecasts, and news behind it.", icon: TrendingUp },
  { title: "Built for India", body: "NSE/BSE equities and indices only — no US stocks, crypto, or forex in this MVP.", icon: ShieldCheck },
  { title: "Comfortable saying no", body: 'When evidence is thin or contradictory, you get "no clear opportunity," not a forced pick.', icon: XCircle },
];

export default function LandingPage() {
  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-10">
      <motion.section variants={fadeInUp} className="space-y-4">
        <h1 className="text-3xl font-bold tracking-tight text-text-primary sm:text-4xl">
          AI-powered research for Indian equities, built for beginners.
        </h1>
        <p className="max-w-2xl text-text-muted">
          This platform combines cached NSE market data, company fundamentals, financial
          news, technical analysis, and specialist forecasting models with a structured
          multi-analyst review process to produce transparent, evidence-based stock research for
          the Indian market only. You never talk to an AI chatbot here — you fill out a simple
          profile, and the research runs invisibly in the background.
        </p>
        <div className="flex gap-3">
          <Link href="/onboarding">
            <Button>Get started</Button>
          </Link>
        </div>
      </motion.section>

      <motion.section variants={staggerChildren} className="grid gap-4 sm:grid-cols-3">
        {FEATURES.map((f) => (
          <motion.div key={f.title} variants={fadeInUp}>
            <Card className="h-full">
              <f.icon className="mb-2 h-5 w-5 text-accent" />
              <h3 className="font-semibold text-text-primary">{f.title}</h3>
              <p className="mt-1 text-sm text-text-muted">{f.body}</p>
            </Card>
          </motion.div>
        ))}
      </motion.section>

      <motion.section variants={fadeInUp} className="flex items-start gap-3 rounded-lg border border-warning/30 bg-warning-subtle p-4 text-sm text-warning">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <p>
          <strong>Risk disclosure:</strong> This is an AI-powered equity research and educational
          analysis prototype, not registered investment advice. All investments in securities are
          subject to market risk. Past performance and model forecasts do not guarantee future
          results. Review SEBI-registered advisory options before making investment decisions.
        </p>
      </motion.section>
    </motion.div>
  );
}
