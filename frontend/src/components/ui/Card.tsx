export default function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`rounded border bg-white p-4 ${className}`}>{children}</div>;
}
