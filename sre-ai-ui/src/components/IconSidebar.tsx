"use client";

import { useState, useRef, useEffect } from "react";
import {
  LayoutGrid,
  Cloud,
  Sun,
  Moon,
  Bell,
  Gauge,
  ClipboardList,
  LogOut,
} from "lucide-react";
import { useTheme } from "@/contexts/ThemeContext";
import { useAuth } from "@/contexts/AuthContext";

export type IconView = "chat" | "applications" | "managed-services" | "alerts" | "operations" | "approvals";

interface IconSidebarProps {
  activeView: IconView;
  onViewChange: (view: IconView) => void;
  userId?: string;
}

interface NavItem {
  id: IconView;
  icon: React.ElementType | null;
  label: string;
  hidden?: boolean; // set true to hide from sidebar without removing the route/code
}

// Custom AI Chat Icon matching the design
function AiChatIcon({ className }: { className?: string }) {
  return (
    <div className={`relative w-6 h-6 ${className}`}>
      {/* Back speech bubble with star */}
      <svg 
        viewBox="0 0 40 40" 
        className="absolute inset-0 w-full h-full"
        fill="none"
      >
        {/* Gray bubble with A+ */}
        <path 
          d="M8 8C8 5.79086 9.79086 4 12 4H28C30.2091 4 32 5.79086 32 8V20C32 22.2091 30.2091 24 28 24H20L14 30V24H12C9.79086 24 8 22.2091 8 20V8Z" 
          fill="#6B7280"
        />
        <text x="16" y="17" fontSize="10" fill="white" fontWeight="bold">A</text>
        <text x="23" y="14" fontSize="7" fill="white" fontWeight="bold">+</text>
      </svg>
      {/* Front gradient bubble */}
      <svg 
        viewBox="0 0 40 40" 
        className="absolute inset-0 w-full h-full"
        fill="none"
      >
        <defs>
          <linearGradient id="chatGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#818CF8" />
            <stop offset="50%" stopColor="#A78BFA" />
            <stop offset="100%" stopColor="#F472B6" />
          </linearGradient>
        </defs>
        <path 
          d="M14 16C14 13.7909 15.7909 12 18 12H34C36.2091 12 38 13.7909 38 16V28C38 30.2091 36.2091 32 34 32H26L20 38V32H18C15.7909 32 14 30.2091 14 28V16Z" 
          fill="url(#chatGradient)"
        />
      </svg>
    </div>
  );
}

// Navigation items (chat is separate at bottom)
const navItems: NavItem[] = [
  { id: "applications", icon: LayoutGrid, label: "Applications" },
  { id: "managed-services", icon: Cloud, label: "Managed\nServices" },
  { id: "alerts", icon: Bell, label: "Alerts" },
  { id: "operations", icon: Gauge, label: "Operations" },
  { id: "approvals", icon: ClipboardList, label: "Approvals" },
];

export function IconSidebar({ activeView, onViewChange, userId }: IconSidebarProps) {
  const [hoveredItem, setHoveredItem] = useState<IconView | null>(null);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const { isDark, toggleTheme } = useTheme();
  const { logout } = useAuth();

  // Close user menu on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setShowUserMenu(false);
      }
    }
    if (showUserMenu) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showUserMenu]);

  // Get user initial for avatar
  const getInitial = (id: string) => {
    if (!id) return "U";
    const namePart = id.includes("@") ? id.split("@")[0] : id;
    const cleanName = namePart.includes("-") ? namePart.split("-").pop() || namePart : namePart;
    return cleanName.charAt(0).toUpperCase();
  };
  const userInitial = getInitial(userId || "");

  const renderNavItem = (item: NavItem) => {
    const isActive = activeView === item.id;
    const isHovered = hoveredItem === item.id;
    const Icon = item.icon;

    return (
      <button
        key={item.id}
        onClick={() => onViewChange(item.id)}
        onMouseEnter={() => setHoveredItem(item.id)}
        onMouseLeave={() => setHoveredItem(null)}
        suppressHydrationWarning
        className={`
          w-full flex flex-col items-center justify-center py-4 px-2 transition-all duration-200
          ${isHovered ? "bg-[#1a1f2e]" : ""}
          ${isActive ? "border-l-2 border-[#90EE90]" : "border-l-2 border-transparent"}
        `}
      >
        {Icon && (
          <Icon 
            suppressHydrationWarning
            className={`w-6 h-6 mb-1.5 ${isActive ? "text-[#90EE90]" : "text-white"}`} 
          />
        )}
        <span suppressHydrationWarning className={`text-[10px] text-center leading-tight whitespace-pre-line ${isActive ? "text-[#90EE90]" : "text-white"}`}>
          {item.label}
        </span>
      </button>
    );
  };

  const isChatActive = activeView === "chat";
  const isChatHovered = hoveredItem === "chat";

  return (
    <aside className="h-full w-20 bg-[#0d1117] flex flex-col border-r border-gray-800/60 flex-shrink-0">
      {/* Logo at top */}
      <div className="py-4 flex items-center justify-center border-b border-gray-800/60">
        <span className="text-[#90EE90] font-bold text-2xl">SOP</span>
      </div>

      {/* Navigation items */}
      <nav className="flex flex-col flex-1">
        {navItems.filter(item => !item.hidden).map(renderNavItem)}
      </nav>

      {/* Footer with chat and user avatar */}
      <div className="border-t border-gray-800/60">
        {/* AI Chat button */}
        <button
          onClick={() => onViewChange("chat")}
          onMouseEnter={() => setHoveredItem("chat")}
          onMouseLeave={() => setHoveredItem(null)}
          suppressHydrationWarning
          className={`
            w-full flex flex-col items-center justify-center py-4 px-2 transition-all duration-200
            ${isChatHovered ? "bg-[#1a1f2e]" : ""}
            ${isChatActive ? "border-l-2 border-[#90EE90]" : "border-l-2 border-transparent"}
          `}
        >
          <AiChatIcon className="mb-1.5" />
          <span suppressHydrationWarning className={`text-[10px] text-center ${isChatActive ? "text-[#90EE90]" : "text-white"}`}>
            AI Chat
          </span>
        </button>

        {/* Theme toggle */}
        <div className="flex justify-center py-2">
          <button
            onClick={toggleTheme}
            className="w-9 h-9 rounded-lg flex items-center justify-center hover:bg-[#1a1f2e] transition-colors"
            title={isDark ? "Switch to light mode" : "Switch to dark mode"}
          >
            {isDark ? (
              <Sun className="w-5 h-5 text-amber-400" />
            ) : (
              <Moon className="w-5 h-5 text-gray-400" />
            )}
          </button>
        </div>

        {/* User avatar with popup menu */}
        <div ref={userMenuRef} className="relative flex justify-center pb-4">
          <button
            onClick={() => setShowUserMenu(v => !v)}
            title={userId || "User"}
            className="w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center text-white text-xs font-medium hover:ring-2 hover:ring-[#90EE90]/60 transition-all"
          >
            {userInitial}
          </button>

          {/* Popup menu — opens to the right */}
          {showUserMenu && (
            <div className="absolute bottom-0 left-full ml-2 w-44 bg-[#1a1f2e] border border-gray-700 rounded-lg shadow-xl z-50 overflow-hidden">
              {/* User info */}
              <div className="px-3 py-2.5 border-b border-gray-700">
                <p className="text-[11px] text-gray-400 truncate">{userId || "User"}</p>
              </div>
              {/* Logout */}
              <button
                onClick={() => { setShowUserMenu(false); logout(); }}
                className="flex items-center gap-2 w-full px-3 py-2 text-xs text-gray-300 hover:bg-red-900/40 hover:text-red-300 transition-colors"
              >
                <LogOut className="w-3.5 h-3.5 flex-shrink-0" />
                Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
