import Link from "next/link";
import { Activity, FolderGit2, Hash, ListChecks } from "lucide-react";
import {
  getProjectBoard,
  getProjects,
  type Board,
  type Project,
} from "@/lib/api";
import { StatusBadge } from "@/components/status-badge";
import { TokenStat } from "@/components/token-stat";
import { DurationStat } from "@/components/duration-stat";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const RUNNING = new Set(["accepted", "running"]);

function StatCard({
  icon: Icon,
  title,
  value,
  hint,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-2">
        <CardDescription className="flex items-center gap-2">
          <Icon className="size-4" />
          {title}
        </CardDescription>
        <CardTitle className="text-2xl tabular-nums">{value}</CardTitle>
      </CardHeader>
      {hint ? (
        <CardContent className="pt-0 text-xs text-muted-foreground">
          {hint}
        </CardContent>
      ) : null}
    </Card>
  );
}

export default async function DashboardPage() {
  let projects: Project[] = [];
  let error: string | null = null;
  try {
    projects = await getProjects();
  } catch (e) {
    error = e instanceof Error ? e.message : "worker injoignable";
  }

  // Boards (tokens + stories) en parallèle ; tolérant aux erreurs par projet.
  const boards = await Promise.all(
    projects.map((p) =>
      getProjectBoard(p.name).catch(() => null as Board | null),
    ),
  );

  const running = projects.filter((p) =>
    RUNNING.has(p.pipeline_status ?? ""),
  ).length;
  const awaiting = projects.filter(
    (p) => p.pipeline_status === "awaiting_approval",
  ).length;

  const tokens = { input: 0, output: 0 };
  let storiesDone = 0;
  let storiesTotal = 0;
  for (const b of boards) {
    if (!b) continue;
    if (b.pipeline?.tokens) {
      tokens.input += b.pipeline.tokens.input;
      tokens.output += b.pipeline.tokens.output;
    }
    for (const e of b.epics) {
      for (const s of e.stories) {
        storiesTotal += 1;
        if (s.status === "done") storiesDone += 1;
      }
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="text-muted-foreground">
          Vue d&apos;ensemble de la tour de contrôle ai-to-boost.
        </p>
      </div>

      {error ? (
        <Card className="shadow-sm">
          <CardContent className="py-6 text-center text-sm text-destructive">
            Worker injoignable — {error}
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={FolderGit2} title="Projets" value={projects.length} />
        <StatCard
          icon={Activity}
          title="Pipelines"
          value={running}
          hint={awaiting ? `${awaiting} en attente de jalon` : "actifs"}
        />
        <StatCard
          icon={ListChecks}
          title="Stories terminées"
          value={`${storiesDone}/${storiesTotal}`}
        />
        <StatCard
          icon={Hash}
          title="Tokens cumulés"
          value={
            tokens.input || tokens.output ? (
              <TokenStat tokens={tokens} className="text-2xl" />
            ) : (
              "—"
            )
          }
        />
      </div>

      <Card className="shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Projets</CardTitle>
          <CardDescription>État des pipelines par projet.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-1.5">
          {projects.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              Aucun projet. Créez-en un depuis la page Projets.
            </p>
          ) : (
            projects.map((p, i) => (
              <Link
                key={p.name}
                href={`/projects/${encodeURIComponent(p.name)}`}
                className="flex items-center justify-between gap-2 rounded-md border bg-background px-3 py-2 text-sm transition-colors hover:bg-accent"
              >
                <span className="min-w-0 truncate font-medium">{p.name}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <DurationStat seconds={boards[i]?.pipeline?.duration_s} />
                  <TokenStat tokens={boards[i]?.pipeline?.tokens} />
                  <StatusBadge
                    status={
                      p.pipeline_status
                        ? p.pipeline_phase
                          ? `${p.pipeline_status} · ${p.pipeline_phase}`
                          : p.pipeline_status
                        : null
                    }
                  />
                </span>
              </Link>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
