import { LoginForm } from "@/components/login-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  return (
    <main className="flex min-h-dvh items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>ai-to-boost</CardTitle>
          <CardDescription>Tour de contrôle — connexion</CardDescription>
        </CardHeader>
        <CardContent>
          <LoginForm error={Boolean(error)} />
        </CardContent>
      </Card>
    </main>
  );
}
