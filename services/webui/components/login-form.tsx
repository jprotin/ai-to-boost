"use client";

import { login } from "@/app/login/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function LoginForm({ error }: { error?: boolean }) {
  return (
    <form action={login} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor="username">Identifiant</Label>
        <Input id="username" name="username" autoComplete="username" required />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="password">Mot de passe</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
        />
      </div>
      {error ? (
        <p className="text-sm text-destructive">Identifiants invalides.</p>
      ) : null}
      <Button type="submit" className="mt-2">
        Se connecter
      </Button>
    </form>
  );
}
