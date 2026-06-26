import { Badge } from "@/components/ui/badge";

type Variant = "default" | "secondary" | "destructive" | "outline";

// Mapping statut (story/epic/pipeline) → variante de badge shadcn.
const VARIANT: Record<string, Variant> = {
  done: "default",
  error: "destructive",
  "in-progress": "secondary",
  review: "secondary",
  "ready-for-dev": "secondary",
  running: "secondary",
  awaiting_approval: "secondary",
  accepted: "secondary",
  backlog: "outline",
  stopped: "outline",
};

export function StatusBadge({
  status,
  className,
}: {
  status?: string | null;
  className?: string;
}) {
  if (!status) {
    return (
      <Badge variant="outline" className={className}>
        —
      </Badge>
    );
  }
  return (
    <Badge variant={VARIANT[status] ?? "secondary"} className={className}>
      {status}
    </Badge>
  );
}
