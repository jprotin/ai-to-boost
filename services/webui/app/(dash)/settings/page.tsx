import { LogOut } from "lucide-react";
import { auth } from "@/auth";
import { getAvailableModels, getHealth } from "@/lib/health";
import { logout } from "@/lib/auth-actions";
import { ThemeSelect } from "@/components/theme-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

function HealthBadge({ ok }: { ok: boolean }) {
  return ok ? (
    <Badge variant="default">OK</Badge>
  ) : (
    <Badge variant="destructive">indisponible</Badge>
  );
}

export default async function SettingsPage() {
  const session = await auth();
  const [health, models] = await Promise.all([getHealth(), getAvailableModels()]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Paramètres</h1>
        <p className="text-muted-foreground">Backend, modèles, apparence et compte.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-base">Backend</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span>Worker (pipelines / projets)</span>
              <HealthBadge ok={health.worker} />
            </div>
            <div className="flex items-center justify-between">
              <span>Bridge (Claude forfait)</span>
              <HealthBadge ok={health.bridge} />
            </div>
            <div className="flex items-center justify-between">
              <span>LiteLLM (modèles locaux)</span>
              <HealthBadge ok={health.litellm} />
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-base">Modèles disponibles</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {models.length === 0 ? (
              <span className="text-sm text-muted-foreground">
                Aucun modèle disponible (bridge / LM Studio).
              </span>
            ) : (
              models.map((m) => (
                <Badge key={m.id} variant="secondary">
                  {m.label}
                </Badge>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-base">Apparence</CardTitle>
          </CardHeader>
          <CardContent>
            <ThemeSelect />
          </CardContent>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-base">Compte</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center justify-between text-sm">
            <span>Connecté en tant que « {session?.user?.name} »</span>
            <form action={logout}>
              <Button type="submit" variant="outline" size="sm">
                <LogOut className="size-4" />
                Déconnexion
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      <p className="text-xs text-muted-foreground">
        ai-to-boost — tour de contrôle (ADR 0005/0006). Remplace bmad-ui.
      </p>
    </div>
  );
}
