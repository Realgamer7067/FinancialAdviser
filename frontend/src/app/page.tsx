"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { AlertTriangle, ShieldCheck, TrendingUp, XCircle } from "lucide-react";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import { fadeInUp, staggerChildren } from "@/lib/motion";

const STEPS = [
  { n: "1", title: "Add what you hold", body: "Import each account by CSV or by hand, or connect Angel One from a terminal on this computer. Nothing is guessed." },
  { n: "2", title: "Tell us your finances", body: "Income, spending, reserve, loans and how you feel about losses. Anything you leave blank stays \"unknown\", and limits what is suggested." },
  { n: "3", title: "Read the review", body: "A dated review of what changed and what to check. \"No change needed\" is a normal answer." },
];

const PROMISES = [
  { title: "Read-only", body: "This app never places or changes an order. You act in Angel One yourself.", icon: ShieldCheck },
  { title: "Evidence with dates", body: "Prices, holdings and each review carry their own date, so you can see how fresh they are.", icon: TrendingUp },
  { title: "Honest about what it cannot see", body: "Missing values, unmatched holdings and unproven signals are shown beside the answer, not hidden.", icon: XCircle },
];

export default function LandingPage() {
  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="mx-auto max-w-4xl space-y-10">
      <motion.section variants={fadeInUp} className="space-y-4">
        <h1 className="text-3xl font-bold tracking-tight text-text-primary sm:text-4xl">
          A private, read-only review of your Indian investments.
        </h1>
        <p className="max-w-2xl text-text-muted">
          See what you hold across your accounts, what has changed, and what is worth checking, for stocks, ETFs, mutual
          funds and the rest. Built for your own money, with no chatbot: fixed rules do the checking, and every number comes
          with its date.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link href="/holdings"><Button>Add your holdings</Button></Link>
          <Link href="/overview"><Button variant="secondary">Go to Overview</Button></Link>
        </div>
      </motion.section>

      <motion.section variants={staggerChildren} aria-label="How it works" className="grid gap-4 sm:grid-cols-3">
        {STEPS.map((st) => (
          <motion.div key={st.n} variants={fadeInUp}>
            <Card className="h-full">
              <p className="mb-1 text-xs font-medium text-accent">Step {st.n}</p>
              <h2 className="font-semibold text-text-primary">{st.title}</h2>
              <p className="mt-1 text-sm text-text-muted">{st.body}</p>
            </Card>
          </motion.div>
        ))}
      </motion.section>

      <motion.section variants={staggerChildren} aria-label="What to expect" className="grid gap-4 sm:grid-cols-3">
        {PROMISES.map((f) => (
          <motion.div key={f.title} variants={fadeInUp} className="flex gap-3">
            <f.icon aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
            <div>
              <h2 className="text-sm font-semibold text-text-primary">{f.title}</h2>
              <p className="mt-0.5 text-sm text-text-muted">{f.body}</p>
            </div>
          </motion.div>
        ))}
      </motion.section>

      <motion.section variants={fadeInUp} className="flex items-start gap-3 rounded-lg border border-warning/30 bg-warning-subtle p-4 text-sm text-warning">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <p>
          <strong>Risk disclosure:</strong> This is a personal analysis tool, not registered investment advice. All
          investments are subject to market risk. Past performance and model forecasts do not guarantee future results.
          Consider a SEBI-registered adviser before making investment decisions.
        </p>
      </motion.section>
    </motion.div>
  );
}
