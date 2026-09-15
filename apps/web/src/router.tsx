import {
  createRouter,
  createRootRoute,
  createRoute,
} from "@tanstack/react-router";
import { AppLayout } from "@/components/layout/app-layout";
import { BoardPage } from "@/pages/board";
import { SessionPage } from "@/pages/session";
import { SettingsPage } from "@/pages/settings";
import TestCostViz from "@/pages/test-cost-viz";
import { ProjectSettingsPage } from "@/pages/project-settings";

const rootRoute = createRootRoute({
  component: AppLayout,
});

const boardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: BoardPage,
});

const sessionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/session/$sessionId",
  component: SessionPage,
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: SettingsPage,
});

const projectSettingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/settings",
  component: ProjectSettingsPage,
});

const testCostVizRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/test-cost-viz",
  component: TestCostViz,
});

const routeTree = rootRoute.addChildren([boardRoute, sessionRoute, settingsRoute, projectSettingsRoute, testCostVizRoute]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
