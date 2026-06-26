import { Card, CardContent } from "@/components/ui/card";

export default async function ProjectDetailPage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = await params;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{decodeURIComponent(name)}</h1>
        <p className="text-muted-foreground">
          Epics/stories, état du pipeline et chat dédié — à venir (C3.3 / C3.4).
        </p>
      </div>
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">
          Détail projet à implémenter (board + pipeline + chat projet).
        </CardContent>
      </Card>
    </div>
  );
}
