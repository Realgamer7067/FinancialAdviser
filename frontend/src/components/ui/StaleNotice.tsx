// Shown above a calculated result whose inputs have since been edited. The result stays visible (it is still a true
// answer to the earlier question) but is plainly marked as out of date until it is run again.
export default function StaleNotice({ stale, children }: { stale: boolean; children: React.ReactNode }) {
  if (!stale) return <>{children}</>;
  return (
    <div>
      <p role="status" className="mb-2 rounded-md border border-warning bg-warning-subtle px-3 py-2 text-sm text-warning">
        You changed the inputs after this was calculated, so it no longer matches them. Run it again to update.
      </p>
      <div aria-hidden={false} className="opacity-60">{children}</div>
    </div>
  );
}
