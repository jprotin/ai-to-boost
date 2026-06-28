import Link from "next/link";
import { getProjects, type Project } from "@/lib/api";
import { CreateProjectDialog } from "@/components/create-project-dialog";
import { DeleteProjectButton } from "@/components/delete-project-button";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default async function ProjectsPage() {
  let projects: Project[] = [];
  let error: string | null = null;
  try {
    projects = await getProjects();
  } catch (e) {
    error = e instanceof Error ? e.message : "worker injoignable";
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Projets</h1>
          <p className="text-muted-foreground">
            Projets pilotés par BMAD (lecture via le worker).
          </p>
        </div>
        <CreateProjectDialog />
      </div>

      {error ? (
        <Card className="shadow-sm">
          <CardContent className="py-10 text-center text-sm text-destructive">
            Impossible de charger les projets — {error}
          </CardContent>
        </Card>
      ) : projects.length === 0 ? (
        <Card className="shadow-sm">
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Aucun projet enregistré. Créez-en un avec le bouton{" "}
            <strong>Nouveau projet</strong> (ou en CLI&nbsp;:{" "}
            <code className="rounded bg-muted px-1">ai2b new &lt;nom&gt;</code>).
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {projects.map((p) => (
            <Card
              key={p.name}
              className="h-full shadow-sm transition-shadow hover:border-ring/40 hover:shadow-md"
            >
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between gap-2">
                  <Link
                    href={`/projects/${encodeURIComponent(p.name)}`}
                    className="min-w-0 flex-1 hover:underline"
                  >
                    <CardTitle className="truncate text-base">{p.name}</CardTitle>
                  </Link>
                  <div className="flex items-center gap-1">
                    {p.active ? <Badge variant="secondary">actif</Badge> : null}
                    <DeleteProjectButton name={p.name} />
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Base</span>
                  <code className="text-xs">{p.base_branch ?? "—"}</code>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Pipeline</span>
                  <StatusBadge
                    status={
                      p.pipeline_status
                        ? p.pipeline_phase
                          ? `${p.pipeline_status} · ${p.pipeline_phase}`
                          : p.pipeline_status
                        : null
                    }
                  />
                </div>
                {!p.exists ? (
                  <Badge variant="destructive">répertoire absent</Badge>
                ) : null}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
