"use client";

import { useState, useCallback, useEffect } from "react";
import { usePathname } from "next/navigation";
import { IconSidebar, type IconView } from "./IconSidebar";
import { ChatInterface } from "./ChatInterface";
import { ApplicationsView } from "./views/ApplicationsView";
import { ManagedServicesView } from "./views/ManagedServicesView";
import { AlertsView } from "./views/AlertsView";
import { OperationsView } from "./views/OperationsView";
import { DependencyApprovalsView } from "./views/DependencyApprovalsView";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import { ViewContextProvider, useViewContext } from "@/contexts/ViewContext";
import { ChatSlideOver, type ChatSlideOverMode } from "./ChatSlideOver";
import { MessageCircle } from "lucide-react";
import type { AgentConfig } from "@/types";

interface MainLayoutProps {
  initialSessionId?: string;
  initialAgents?: AgentConfig[];
}

function pathnameToView(pathname: string): IconView {
  if (pathname.startsWith("/applications")) return "applications";
  if (pathname.startsWith("/managedservices")) return "managed-services";
  if (pathname.startsWith("/alerts")) return "alerts";
  if (pathname.startsWith("/operations")) return "operations";
  if (pathname.startsWith("/approvals")) return "approvals";
  return "chat";
}

function viewToPathname(view: IconView): string {
  switch (view) {
    case "applications": return "/applications";
    case "managed-services": return "/managedservices";
    case "alerts": return "/alerts";
    case "operations": return "/operations";
    case "approvals": return "/approvals";
    default: return "/";
  }
}

export function MainLayout({ initialSessionId: _initialSessionId, initialAgents }: MainLayoutProps) {
  return (
    <ViewContextProvider>
      <MainLayoutInner initialSessionId={_initialSessionId} initialAgents={initialAgents} />
    </ViewContextProvider>
  );
}

function MainLayoutInner({ initialSessionId, initialAgents }: { initialSessionId?: string; initialAgents?: AgentConfig[] }) {
  const { user } = useAuth();
  const { isDark } = useTheme();
  const userId = user?.loginId ?? "";
  const pathname = usePathname();
  const { setActiveView: setViewContextActiveView, selectedApplication, selectedManagedService } = useViewContext();
  const [chatMode, setChatMode] = useState<ChatSlideOverMode>("closed");

  // Derive initial view from the current URL path — usePathname() is SSR-safe
  const [activeView, setActiveView] = useState<IconView>(() => pathnameToView(pathname));
  const [previousView, setPreviousView] = useState<IconView | null>(null);

  // Sync activeView to ViewContext synchronously (no useEffect lag)
  const syncView = useCallback((view: IconView) => {
    setActiveView(view);
    setViewContextActiveView(view as Parameters<typeof setViewContextActiveView>[0]);
  }, [setViewContextActiveView]);

  // Initial sync on mount
  useEffect(() => {
    setViewContextActiveView(activeView as Parameters<typeof setViewContextActiveView>[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Handle browser back/forward buttons
  useEffect(() => {
    const onPopState = () => {
      const view = pathnameToView(window.location.pathname);
      syncView(view);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [syncView]);


  const handleViewChange = useCallback((view: IconView) => {
    setPreviousView(activeView);
    syncView(view);
    const targetPath = viewToPathname(view);
    if (window.location.pathname !== targetPath) {
      window.history.pushState(null, "", targetPath);
    }
  }, [activeView, syncView]);

  const renderContent = () => {
    switch (activeView) {
      case "chat":
        return <ChatInterface initialSessionId={initialSessionId} initialAgents={initialAgents} />;
      case "applications":
        return <ApplicationsView onNavigateToChat={() => handleViewChange("chat")} />;
      case "managed-services":
        return <ManagedServicesView />;
      case "alerts":
        return <AlertsView />;
      case "operations":
        return <OperationsView />;
      case "approvals":
        return <DependencyApprovalsView />;
      default:
        return <ChatInterface initialSessionId={initialSessionId} initialAgents={initialAgents} />;
    }
  };

  // Show FAB on data views only (applications, managed-services)
  const isDataView = activeView === "applications" || activeView === "managed-services";

  // Auto-close chat when navigating away from data views
  // (don't destroy — just hide so CopilotKit session is preserved)
  useEffect(() => {
    if (!isDataView) {
      setChatMode("closed");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDataView]);

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50 dark:bg-[#0d1117]">
      <IconSidebar
        activeView={activeView}
        onViewChange={handleViewChange}
        userId={userId}
      />
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <div className="h-full transition-transform duration-500 ease-out translate-x-0">
          {renderContent()}
        </div>
      </main>

      {/* Floating Chat Button (FAB) — only on data views */}
      {isDataView && chatMode === "closed" && (
        <button
          onClick={() => setChatMode("open")}
          className="fixed bottom-20 right-6 z-30 w-12 h-12 rounded-full bg-gradient-to-br from-[#0071CE] to-[#004fa3] text-white shadow-lg hover:shadow-xl hover:scale-105 active:scale-95 transition-all flex items-center justify-center group"
          title={`Ask AI about ${activeView === "applications" ? "applications" : "managed services"}`}
        >
          <MessageCircle className="w-5 h-5 group-hover:scale-110 transition-transform" />
          {(selectedApplication || selectedManagedService) && (
            <span className="absolute -top-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-white dark:border-[#0d1117] animate-pulse" />
          )}
        </button>
      )}

      {/* Chat Slide-Over Panel — always mounted to preserve CopilotKit session,
          mode controlled by chatMode state, auto-closes on non-data views */}
      <ChatSlideOver
        mode={isDataView ? chatMode : "closed"}
        onModeChange={setChatMode}
      />
    </div>
  );
}
