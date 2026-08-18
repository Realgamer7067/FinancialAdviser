"use client";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-sm space-y-4 text-center">
      <h1 className="text-xl font-semibold">Something went wrong</h1>
      <p className="text-sm text-slate-500">
        An unexpected error occurred while rendering this page. Retrying usually resolves it.
      </p>
      <button
        onClick={reset}
        className="rounded bg-brand-600 px-4 py-2 text-white hover:bg-brand-700"
      >
        Try again
      </button>
    </div>
  );
}
