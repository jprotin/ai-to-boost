"use client"; // Les error boundaries doivent être des Client Components (Next 16)

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// Next 16 : le prop de reprise s'appelle `unstable_retry` (ex-`reset`).
export default function Error({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="max-w-md shadow-sm">
        <CardHeader>
          <CardTitle>Une erreur est survenue</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            Le chargement a échoué. Tu peux réessayer — si le problème persiste,
            vérifie l’état des services dans Paramètres.
          </p>
          <Button onClick={() => unstable_retry()}>Réessayer</Button>
        </CardContent>
      </Card>
    </div>
  );
}
