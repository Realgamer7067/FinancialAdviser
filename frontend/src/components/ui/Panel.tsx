import Card from "./Card";

// Thin wrapper over Card -- kept as a separate named export since it's used
// as `import { Panel, Row } from "@/components/ui/Panel"` in a couple of
// places; the styling itself now lives in Card (Phase 1 consolidation).
export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <Card title={title}>{children}</Card>;
}

export function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-1 text-sm">
      <dt className="text-text-muted">{label}</dt>
      <dd className="font-medium text-text-primary">{value}</dd>
    </div>
  );
}
