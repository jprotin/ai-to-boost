import { Card, CardContent } from "@/components/ui/card";

export default function ProjectsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Projets</h1>
        <p className="text-muted-foreground">
          Projets pilotés par BMAD — liste à venir en C3.2.
        </p>
      </div>
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">
          Liste des projets à implémenter (C3.2, via l&apos;API lecture du worker).
        </CardContent>
      </Card>
    </div>
  );
}
