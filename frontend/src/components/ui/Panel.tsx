export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border bg-white p-4">
      <h3 className="mb-2 font-medium">{title}</h3>
      {children}
    </div>
  );
}

export function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
