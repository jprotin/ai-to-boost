"use client";

import { Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

export type Conversation = { id: string; title: string; model: string };

export function ConversationList({
  conversations,
  activeId,
  onNew,
  onSelect,
  onDelete,
}: {
  conversations: Conversation[];
  activeId: string | null;
  onNew: () => void;
  onSelect: (c: Conversation) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="flex h-full flex-col gap-2">
      <Button variant="outline" className="justify-start" onClick={onNew}>
        <Plus className="size-4" />
        Nouvelle conversation
      </Button>
      <div className="flex-1 space-y-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <p className="px-2 py-4 text-xs text-muted-foreground">
            Aucune conversation enregistrée.
          </p>
        ) : (
          conversations.map((c) => (
            <div
              key={c.id}
              className={cn(
                "group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm",
                activeId === c.id ? "bg-accent" : "hover:bg-accent/50",
              )}
            >
              <button
                className="min-w-0 flex-1 truncate text-left"
                onClick={() => onSelect(c)}
                title={c.title}
              >
                {c.title}
              </button>
              <AlertDialog>
                <AlertDialogTrigger className="opacity-0 group-hover:opacity-100">
                  <Trash2 className="size-4 text-muted-foreground hover:text-destructive" />
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Supprimer la conversation ?</AlertDialogTitle>
                    <AlertDialogDescription>
                      « {c.title} » sera définitivement supprimée.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Annuler</AlertDialogCancel>
                    <AlertDialogAction onClick={() => onDelete(c.id)}>
                      Supprimer
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
