"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

const OPTIONS: [string, string][] = [
  ["light", "Clair"],
  ["dark", "Sombre"],
  ["system", "Système"],
];

export function ThemeSelect() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  // Garde anti-hydratation next-themes (le thème n'est connu que côté client).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), []);

  return (
    <div className="flex gap-2">
      {OPTIONS.map(([value, label]) => (
        <Button
          key={value}
          size="sm"
          variant={mounted && theme === value ? "default" : "outline"}
          onClick={() => setTheme(value)}
        >
          {label}
        </Button>
      ))}
    </div>
  );
}
