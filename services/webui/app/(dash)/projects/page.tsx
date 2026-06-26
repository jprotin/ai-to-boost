import Link from "next/link";
import { getProjects, type Project } from "@/lib/api";
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
      <div>
        <h1 className="text-2xl font-semibold">Projets</h1>
        <p className="text-muted-foreground">
          Projets pilotés par BMAD (lecture via le worker).
        </p>
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
            Aucun projet enregistré. Créez-en un avec{" "}
            <code className="rounded bg-muted px-1">ai2b new &lt;nom&gt;</code>.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {projects.map((p) => (
            <Link
              key={p.name}
              href={`/projects/${encodeURIComponent(p.name)}`}
              className="group"
            >
              <Card className="h-full shadow-sm transition-shadow group-hover:border-ring/40 group-hover:shadow-md">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="truncate text-base">{p.name}</CardTitle>
                    {p.active ? <Badge variant="secondary">actif</Badge> : null}
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
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
