import { SidebarTrigger } from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";
import type { SessionEntry } from "@/types";

interface HarnessHeaderProps {
	session?: SessionEntry | null;
}

export function HarnessHeader({ session }: HarnessHeaderProps) {
	return (
		<header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background px-4">
			<SidebarTrigger className="cursor-pointer" />
			{session && (
				<div className="flex items-center gap-2">
					<span className="font-medium">
						{session.workspaceName || session.id.slice(0, 8)}
					</span>
					<Badge variant="outline" className="text-xs">
						{session.status}
					</Badge>
				</div>
			)}
		</header>
	);
}
