import { notFound } from "next/navigation";
import { getProjectBoard, type Board } from "@/lib/api";
import { ProjectView } from "@/components/project-view";
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

  const view: Board = board ?? {
    name: projectName,
    pipeline: {},
    epics: [],
  };

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardContent className="flex flex-wrap items-center gap-3 py-4">
          <h1 className="text-xl font-semibold">{projectName}</h1>
          {view.pipeline?.status ? (
            <StatusBadge status={view.pipeline.status} />
          ) : null}
          {view.pipeline?.phase ? (
            <span className="text-sm text-muted-foreground">
              phase : {view.pipeline.phase}
            </span>
          ) : null}
          {view.pipeline?.branch ? (
            <code className="ml-auto text-xs text-muted-foreground">
              {view.pipeline.branch}
            </code>
          ) : null}
        </CardContent>
      </Card>

      {error ? (
        <Card className="shadow-sm">
          <CardContent className="py-10 text-center text-sm text-destructive">
            Impossible de charger le projet — {error}
          </CardContent>
        </Card>
      ) : (
        <ProjectView name={projectName} board={view} />
      )}
    </div>
  );
}
