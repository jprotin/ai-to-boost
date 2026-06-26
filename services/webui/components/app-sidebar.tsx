"use client";

import { FolderKanban, LayoutDashboard, MessageSquare, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/projects", label: "Projets", icon: FolderKanban },
  { href: "/settings", label: "Paramètres", icon: Settings },
];

export function AppSidebar() {
  const pathname = usePathname();
  return (
    <aside className="hidden w-56 shrink-0 border-r bg-sidebar p-3 md:block">
      <div className="px-2 py-3 text-lg font-semibold">ai-to-boost</div>
      <nav className="flex flex-col gap-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
              )}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
