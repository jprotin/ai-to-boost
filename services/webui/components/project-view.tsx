"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ArchiveView } from "@/components/archive-view";
import { ArtifactsView } from "@/components/artifacts-view";
import { Chat } from "@/components/chat";
import { CollectButton } from "@/components/collect-button";
import { JalonBanner } from "@/components/jalon-banner";
import { LaunchPipeline } from "@/components/launch-pipeline";
import { PipelineProgress } from "@/components/pipeline-progress";
import { ProjectBoard } from "@/components/project-board";
import { StatusBadge } from "@/components/status-badge";
import { TokenStat } from "@/components/token-stat";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Board } from "@/lib/api";

const ACTIVE = new Set(["accepted", "running", "awaiting_approval"]);

export function ProjectView({
  name,
  board: initial,
}: {
  name: string;
  board: Board;
}) {
  const [board, setBoard] = useState(initial);
  const [tab, setTab] = useState(
    initial.pipeline?.status === "awaiting_approval" ? "artifacts" : "board",
  );
  const prevStatus = useRef<string | undefined>(initial.pipeline?.status);

  const refetch = useCallback(async () => {
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(name)}/board`);
      if (!r.ok) return;
      const b: Board = await r.json();
      const s = b.pipeline?.status;
      if (s !== prevStatus.current) {
        if (s === "awaiting_approval") {
          toast.info(`Jalon « ${b.pipeline?.phase} » à valider`);
          setTab("artifacts"); // bascule sur la relecture des artefacts au jalon
        } else if (s === "done") toast.success("Pipeline terminé");
        else if (s === "error") toast.error("Pipeline en erreur");
        prevStatus.current = s;
      }
      setBoard(b);
    } catch {
      /* silencieux */
    }
  }, [name]);

  // Polling live tant que le pipeline est actif.
  const active = ACTIVE.has(board.pipeline?.status ?? "");
  useEffect(() => {
    if (!active) return;
    const id = setInterval(refetch, 4000);
    return () => clearInterval(id);
  }, [active, refetch]);

  return (
    <div className="space-y-4">
      <PipelineProgress
        status={board.pipeline?.status}
        phase={board.pipeline?.phase}
        phases={board.phases}
      />

      {board.pipeline?.status === "awaiting_approval" ? (
        <JalonBanner
          name={name}
          phase={board.pipeline.phase}
          onResolved={refetch}
        />
      ) : null}

      {board.pipeline?.acceptance ? (
        <div
          className={`rounded-lg border p-3 text-sm ${
            board.pipeline.acceptance.ok
              ? "border-emerald-500/40 bg-emerald-500/10"
              : "border-amber-500/50 bg-amber-500/10"
          }`}
        >
          <span className="font-medium">
            {board.pipeline.acceptance.ok
              ? "✅ Acceptation — le livrable répond au besoin"
              : "⚠️ Acceptation — à vérifier avant d'approuver"}
          </span>
          {board.pipeline.acceptance.reason ? (
            <span className="mt-0.5 block text-muted-foreground">
              {board.pipeline.acceptance.reason}
            </span>
          ) : null}
          {board.pipeline.acceptance.tests &&
          board.pipeline.acceptance.tests !== "aucun" ? (
            <span className="mt-0.5 block text-xs text-muted-foreground">
              Tests :{" "}
              {board.pipeline.acceptance.tests.startsWith("fail")
                ? "en échec"
                : "OK"}
            </span>
          ) : null}
        </div>
      ) : null}

      {board.pipeline?.status && !ACTIVE.has(board.pipeline.status) ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <StatusBadge status={board.pipeline.status} />
          {board.pipeline.branch ? (
            <code className="text-xs text-muted-foreground">
              {board.pipeline.branch}
            </code>
          ) : null}
          {board.pipeline.tokens ? (
            <span className="flex items-center gap-1 text-muted-foreground">
              <span className="text-xs">Total</span>
              <TokenStat tokens={board.pipeline.tokens} />
            </span>
          ) : null}
          {board.pipeline.status === "done" ? (
            <div className="ml-auto">
              <CollectButton
                name={name}
                branch={board.pipeline.branch}
                onCollected={refetch}
              />
            </div>
          ) : null}
        </div>
      ) : null}

      <Tabs
        value={tab}
        onValueChange={(v) => setTab(String(v))}
        className="space-y-4"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <TabsList>
            <TabsTrigger value="board">Board</TabsTrigger>
            <TabsTrigger value="artifacts">Artefacts</TabsTrigger>
            <TabsTrigger value="archive">Archive</TabsTrigger>
            <TabsTrigger value="chat">Chat projet</TabsTrigger>
          </TabsList>
          <LaunchPipeline name={name} onLaunched={refetch} disabled={active} />
        </div>

        <TabsContent value="artifacts">
          <ArtifactsView
            name={name}
            artifacts={board.pipeline?.artifacts ?? []}
            current={board.pipeline?.awaiting}
          />
        </TabsContent>

        <TabsContent value="board">
          {board.epics.length === 0 ? (
            <Card className="shadow-sm">
              <CardContent className="py-10 text-center text-sm text-muted-foreground">
                Aucun board pour ce projet. Lancez un pipeline ci-dessus.
              </CardContent>
            </Card>
          ) : (
            <ProjectBoard board={board} />
          )}
        </TabsContent>

        <TabsContent value="archive">
          <ArchiveView name={name} />
        </TabsContent>

        <TabsContent value="chat">
          <Chat
            project={name}
            pipeline={{
              status: board.pipeline?.status,
              phase: board.pipeline?.phase,
            }}
            onPipelineAction={refetch}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
