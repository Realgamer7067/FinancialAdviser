"use client";

import { AlertCircle } from "lucide-react";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-sm space-y-4 text-center">
      <EmptyState
        icon={AlertCircle}
        title="Something went wrong"
        message="An unexpected error occurred while rendering this page. Retrying usually resolves it."
      />
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
