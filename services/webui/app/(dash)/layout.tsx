import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { AppSidebar } from "@/components/app-sidebar";
import { MobileNav } from "@/components/mobile-nav";
import { ThemeToggle } from "@/components/theme-toggle";
import { UserMenu } from "@/components/user-menu";

// Protection au niveau du layout (ADR 0005) : évite le middleware (déprécié → `proxy`
// en Next 16) et applique le contrôle de session côté serveur sur tout le groupe.
export default async function DashLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  if (!session?.user) redirect("/login");

  return (
    <div className="flex min-h-dvh">
      <AppSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b px-4">
          <MobileNav />
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            <UserMenu name={session.user.name ?? "utilisateur"} />
          </div>
        </header>
        <main className="min-w-0 flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
