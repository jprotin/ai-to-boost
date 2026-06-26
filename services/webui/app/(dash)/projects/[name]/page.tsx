import { notFound } from "next/navigation";
import { getProjectBoard, type Board } from "@/lib/api";
import { ProjectBoard } from "@/components/project-board";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent } from "@/components/ui/card";

export default async function ProjectDetailPage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = await params;
  const projectName = decodeURIComponent(name);

  let board: Board | null = null;
  let error: string | null = null;
  try {
    board = await getProjectBoard(projectName);
  } catch (e) {
    error = e instanceof Error ? e.message : "worker injoignable";
  }
  if (!error && board === null) notFound();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{projectName}</h1>
        {board?.pipeline?.status ? (
          <StatusBadge status={board.pipeline.status} />
        ) : null}
        {board?.pipeline?.phase ? (
          <span className="text-sm text-muted-foreground">
            phase : {board.pipeline.phase}
          </span>
        ) : null}
        {board?.pipeline?.branch ? (
          <code className="text-xs text-muted-foreground">
            {board.pipeline.branch}
          </code>
        ) : null}
      </div>

      {error ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-destructive">
            Impossible de charger le projet — {error}
          </CardContent>
        </Card>
      ) : !board || board.epics.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Aucun board pour ce projet. Lancez un pipeline avec{" "}
            <code className="rounded bg-muted px-1">ai2b run &quot;…&quot;</code>.
          </CardContent>
        </Card>
      ) : (
        <ProjectBoard board={board} />
      )}
    </div>
  );
}
