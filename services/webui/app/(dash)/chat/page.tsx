import { Card, CardContent } from "@/components/ui/card";

export default function ChatPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Chat</h1>
        <p className="text-muted-foreground">
          Discuter avec Claude (forfait) ou un modèle local — à venir en C3.1.
        </p>
      </div>
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">
          Interface de chat à implémenter (C3.1).
        </CardContent>
      </Card>
    </div>
  );
}
