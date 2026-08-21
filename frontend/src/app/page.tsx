import Link from "next/link";

export default function LandingPage() {
  return (
    <div className="space-y-10">
      <section className="space-y-4">
        <h1 className="text-3xl font-bold text-slate-900">
          AI-powered research for Indian equities, built for beginners.
        </h1>
        <p className="max-w-2xl text-slate-600">
          This platform combines live/historical NSE market data, company fundamentals, financial
          news, technical analysis, and specialist forecasting models with a structured
          multi-analyst review process to produce transparent, evidence-based stock research for
          the Indian market only. You never talk to an AI chatbot here -- you fill out a simple
          profile, and the research runs invisibly in the background.
        </p>
        <div className="flex gap-3">
          <Link href="/onboarding" className="rounded bg-brand-600 px-4 py-2 text-white hover:bg-brand-700">
            Get started
          </Link>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        {[
          { title: "Evidence, not vibes", body: "Every recommendation cites the fundamentals, technicals, forecasts, and news behind it." },
          { title: "Built for India", body: "NSE/BSE equities and indices only -- no US stocks, crypto, or forex in this MVP." },
          { title: "Comfortable saying no", body: "When evidence is thin or contradictory, you get \"no clear opportunity,\" not a forced pick." },
        ].map((c) => (
          <div key={c.title} className="rounded border bg-white p-4">
            <h3 className="font-semibold text-slate-900">{c.title}</h3>
            <p className="mt-1 text-sm text-slate-600">{c.body}</p>
          </div>
        ))}
      </section>

      <section className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <strong>Risk disclosure:</strong> This is an AI-powered equity research and educational
        analysis prototype, not registered investment advice. All investments in securities are
        subject to market risk. Past performance and model forecasts do not guarantee future
        results. Review SEBI-registered advisory options before making investment decisions.
      </section>
    </div>
  );
}
