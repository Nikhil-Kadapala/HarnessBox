import { useNavigate } from "@tanstack/react-router";
import { useSharedSessionManager } from "@/hooks/use-session-manager";
import { SessionBoardApp } from "@/components/session-board/session-board-app";

export function BoardPage() {
  const manager = useSharedSessionManager();
  const navigate = useNavigate();

  const handleSelectSession = (id: string) => {
    manager.switchSession(id);
    navigate({ to: "/session/$sessionId", params: { sessionId: id } });
  };

  return <SessionBoardApp onSelectSession={handleSelectSession} />;
}
