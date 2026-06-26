import { NavLinks } from "@/components/nav-links";

// Sidebar fixe (desktop). Sur mobile, voir MobileNav (Sheet burger).
export function AppSidebar() {
  return (
    <aside className="hidden w-56 shrink-0 border-r bg-sidebar p-3 md:block">
      <div className="px-2 py-3 text-lg font-semibold">ai-to-boost</div>
      <NavLinks />
    </aside>
  );
}
