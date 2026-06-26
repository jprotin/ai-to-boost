"use client";

import { Chat } from "@/components/chat";
import { LaunchPipeline } from "@/components/launch-pipeline";
import { ProjectBoard } from "@/components/project-board";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Board } from "@/lib/api";

export function ProjectView({ name, board }: { name: string; board: Board }) {
  return (
    <Tabs defaultValue="board" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TabsList>
          <TabsTrigger value="board">Board</TabsTrigger>
          <TabsTrigger value="chat">Chat projet</TabsTrigger>
        </TabsList>
        <LaunchPipeline name={name} />
      </div>

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

      <TabsContent value="chat">
        <Chat project={name} />
      </TabsContent>
    </Tabs>
  );
}
