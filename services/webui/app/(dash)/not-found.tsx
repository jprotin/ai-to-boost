import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// base-ui n'accepte pas `asChild` : on stylise le <Link> via buttonVariants.
export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="max-w-md shadow-sm">
        <CardHeader>
          <CardTitle>Page introuvable</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>La page demandée n’existe pas ou a été déplacée.</p>
          <Link href="/" className={buttonVariants()}>
            Retour au tableau de bord
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
