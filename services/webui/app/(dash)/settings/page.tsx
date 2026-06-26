import { Card, CardContent } from "@/components/ui/card";

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Paramètres</h1>
        <p className="text-muted-foreground">
          Modèles, backend, préférences — à venir en C3.6.
        </p>
      </div>
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">
          Paramétrage à implémenter (C3.6).
        </CardContent>
      </Card>
    </div>
  );
}
