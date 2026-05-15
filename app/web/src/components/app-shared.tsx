import type { ReactNode } from "react";
import LayoutDashboard from "lucide-react/dist/esm/icons/layout-dashboard";
import Settings from "lucide-react/dist/esm/icons/settings";
import BookOpen from "lucide-react/dist/esm/icons/book-open";
import HelpCircle from "lucide-react/dist/esm/icons/help-circle";

export type SidebarNavItem = {
	title: string;
	path?: string;
	icon?: ReactNode;
	isActive?: boolean;
	subItems?: SidebarNavItem[];
	onClick?: () => void;
};

export type SidebarNavGroup = {
	label?: string;
	items: SidebarNavItem[];
};

export const navGroups: SidebarNavGroup[] = [
	{
		items: [
			{
				title: "Dashboard",
				path: "#/board",
				icon: <LayoutDashboard />,
				isActive: true,
			},
			{
				title: "Settings",
				path: "#/settings",
				icon: <Settings />,
			},
		],
	},
];

export const footerNavLinks: SidebarNavItem[] = [
	{
		title: "Help",
		path: "https://github.com/Nikhil-Kadapala/HarnessBox",
		icon: <HelpCircle />,
	},
	{
		title: "Documentation",
		path: "https://github.com/Nikhil-Kadapala/HarnessBox/blob/main/README.md",
		icon: <BookOpen />,
	},
];

export const navLinks: SidebarNavItem[] = [
	...navGroups.flatMap((group) =>
		group.items.flatMap((item) =>
			item.subItems?.length ? [item, ...item.subItems] : [item]
		)
	),
	...footerNavLinks,
];
