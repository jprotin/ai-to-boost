"use client";

import { Menu } from "lucide-react";
import { useState } from "react";
import { NavLinks } from "@/components/nav-links";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

// Menu de navigation mobile : burger → Sheet (gauche). Se ferme à la navigation.
export function MobileNav() {
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger className="inline-flex size-9 items-center justify-center rounded-md hover:bg-accent md:hidden">
        <Menu className="size-5" />
        <span className="sr-only">Menu</span>
      </SheetTrigger>
      <SheetContent side="left" className="w-64 p-3">
        <SheetHeader className="p-2">
          <SheetTitle>ai-to-boost</SheetTitle>
        </SheetHeader>
        <NavLinks onNavigate={() => setOpen(false)} />
      </SheetContent>
    </Sheet>
  );
}
