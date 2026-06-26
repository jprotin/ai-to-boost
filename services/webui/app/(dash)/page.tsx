import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="text-muted-foreground">
          Vue d&apos;ensemble de la tour de contrôle ai-to-boost.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Projets</CardTitle>
            <CardDescription>Projets pilotés par BMAD (C3.2).</CardDescription>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Pipelines</CardTitle>
            <CardDescription>État des pipelines en cours (C3.3).</CardDescription>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Chat</CardTitle>
            <CardDescription>Discuter avec Claude ou un LLM local (C3.1).</CardDescription>
          </CardHeader>
        </Card>
      </div>
    </div>
  );
}
