import clsx from "clsx";

export default function Card({
  className,
  title,
  interactive = false,
  children,
}: {
  className?: string;
  title?: string;
  interactive?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={clsx(
        "rounded-lg border border-border bg-surface p-4 shadow-sm",
        interactive && "transition-shadow hover:shadow-md",
        className
      )}
    >
      {title && <h2 className="mb-2 font-medium text-text-primary">{title}</h2>}
      {children}
    </div>
  );
}
