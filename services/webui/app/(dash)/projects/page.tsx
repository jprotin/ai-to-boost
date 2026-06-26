import Link from "next/link";
import { getProjects, type Project } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function statusBadge(p: Project) {
  const s = p.pipeline_status;
  if (!s) return <Badge variant="outline">—</Badge>;
  const variant =
    s === "done"
      ? "default"
      : s === "error"
        ? "destructive"
        : s === "stopped"
          ? "outline"
          : "secondary";
  const label = p.pipeline_phase ? `${s} · ${p.pipeline_phase}` : s;
  return <Badge variant={variant}>{label}</Badge>;
}

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
        <Card>
          <CardContent className="py-10 text-center text-sm text-destructive">
            Impossible de charger les projets — {error}
          </CardContent>
        </Card>
      ) : projects.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Aucun projet enregistré. Créez-en un avec{" "}
            <code className="rounded bg-muted px-1">ai2b new &lt;nom&gt;</code>.
          </CardContent>
        </Card>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nom</TableHead>
                <TableHead>Base</TableHead>
                <TableHead>Dernier pipeline</TableHead>
                <TableHead className="text-right">État</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {projects.map((p) => (
                <TableRow key={p.name}>
                  <TableCell className="font-medium">
                    <Link
                      href={`/projects/${encodeURIComponent(p.name)}`}
                      className="hover:underline"
                    >
                      {p.name}
                    </Link>
                    {p.active ? (
                      <Badge variant="secondary" className="ml-2">
                        actif
                      </Badge>
                    ) : null}
                    {!p.exists ? (
                      <Badge variant="destructive" className="ml-2">
                        absent
                      </Badge>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {p.base_branch ?? "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {p.last_pipeline ?? "—"}
                  </TableCell>
                  <TableCell className="text-right">{statusBadge(p)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
