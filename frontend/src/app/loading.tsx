import { SkeletonCard } from "@/components/ui/Skeleton";

export default function GlobalLoading() {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <SkeletonCard />
      <SkeletonCard />
    </div>
  );
}
