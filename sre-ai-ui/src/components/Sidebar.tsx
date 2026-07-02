"use client";

import { useState, useCallback, useEffect } from "react";
import { MessageSquarePlus, MessageSquare, ChevronLeft, ChevronRight, BookOpen, Link2, Check, ChevronDown, Globe, Bell, Lock } from "lucide-react";
import type { Conversation } from "@/types";
import { useTheme } from "@/contexts/ThemeContext";
import { patchSessionVisibility } from "@/lib/sessions-client";
import { getActiveMonitors } from "@/lib/works-client";

// ─── Known sidebar tag sections ───────────────────────────────────────────────
// Add entries here to show new tag sections in the sidebar.
// Each entry defines the tag name, icon, and default collapse state.
const KNOWN_TAGS: Array<{ name: string; icon: React.ReactNode; defaultCollapsed: boolean }> = [
  { name: "Alert", icon: <Bell className="w-3 h-3" />, defaultCollapsed: true },
  // Future: { name: "Incident", icon: <AlertTriangle className="w-3 h-3" />, defaultCollapsed: true },
];

interface SidebarProps {
  conversations: Conversation[];
  activeSessionId: string;
  userId: string;
  loading: boolean;
  onNewChat: () => void;
  onSelectConversation: (sessionId: string) => void;
  onHowToClick?: () => void;
}

function timeAgo(unixTs: number): string {
  const diff = Date.now() / 1000 - unixTs;
  if (diff < 60) return "Just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(unixTs * 1000).toLocaleDateString();
}

function getGroup(unixTs: number): string {
  const now = Date.now() / 1000;
  const diff = now - unixTs;
  if (diff < 86400) return "Today";
  if (diff < 172800) return "Yesterday";
  if (diff < 604800) return "This week";
  return "Older";
}

const GROUP_ORDER = ["Today", "Yesterday", "This week", "Older"];

export function Sidebar({
  conversations,
  activeSessionId,
  userId,
  loading,
  onNewChat,
  onSelectConversation,
  onHowToClick,
}: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [madePublicId, setMadePublicId] = useState<string | null>(null);
  const [taggedId, setTaggedId] = useState<string | null>(null);
  const [activeMonitors, setActiveMonitors] = useState<Set<string>>(new Set());
  const { theme } = useTheme();
  const isDark = theme === "dark";

  // Fetch actively monitored sessions
  useEffect(() => {
    let isMounted = true;
    async function fetchMonitors() {
      try {
        const { data } = await getActiveMonitors();
        if (isMounted && data) {
          setActiveMonitors(new Set(data));
        }
      } catch (err) {
        console.error("Failed to fetch active monitors", err);
      }
    }
    
    fetchMonitors();
    // Re-fetch monitors periodically
    const interval = setInterval(fetchMonitors, 30000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [activeSessionId]);

  // Section collapse state — only "Today" expanded by default, everything else collapsed
  const [sectionCollapsed, setSectionCollapsed] = useState<Record<string, boolean>>(() => ({
    "Public": true,
    "Personal": false,
    "Today": false,        // expanded — current conversations
    "Yesterday": true,     // collapsed
    "This week": true,     // collapsed
    "Older": true,         // collapsed
    ...Object.fromEntries(KNOWN_TAGS.map(t => [t.name, t.defaultCollapsed])),
  }));

  const [localConvs, setLocalConvs] = useState<Conversation[]>([]);
  // Merge server conversations with any optimistic local updates
  const allConvs = conversations.map(c => {
    const local = localConvs.find(l => l.session_id === c.session_id);
    return local ? { ...c, ...local } : c;
  });

  function copyLink(sessionId: string, e: React.MouseEvent) {
    e.stopPropagation();
    const url = `${window.location.origin}/?session=${encodeURIComponent(sessionId)}`;
    navigator.clipboard.writeText(url).then(() => {
      setCopiedId(sessionId);
      setTimeout(() => setCopiedId(null), 2000);
    });
  }

  const makePublic = useCallback(async (conv: Conversation, e: React.MouseEvent) => {
    e.stopPropagation();
    const newPublic = !conv.public;
    // Optimistic update
    setLocalConvs(prev => {
      const existing = prev.find(l => l.session_id === conv.session_id);
      if (existing) return prev.map(l => l.session_id === conv.session_id ? { ...l, public: newPublic } : l);
      return [...prev, { ...conv, public: newPublic }];
    });
    setMadePublicId(conv.session_id);
    setTimeout(() => setMadePublicId(null), 2000);
    await patchSessionVisibility(conv.session_id, userId, { public: newPublic, tags: conv.tags ?? [] });
  }, [userId]);

  const toggleTag = useCallback(async (conv: Conversation, tagName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const currentTags = conv.tags ?? [];
    const hasTag = currentTags.includes(tagName);
    const newTags = hasTag ? currentTags.filter(t => t !== tagName) : [...currentTags, tagName];
    setLocalConvs(prev => {
      const existing = prev.find(l => l.session_id === conv.session_id);
      if (existing) return prev.map(l => l.session_id === conv.session_id ? { ...l, tags: newTags } : l);
      return [...prev, { ...conv, tags: newTags }];
    });
    setTaggedId(conv.session_id);
    setTimeout(() => setTaggedId(null), 2000);
    await patchSessionVisibility(conv.session_id, userId, { public: conv.public ?? false, tags: newTags });
  }, [userId]);

  const toggleSection = (name: string) => {
    setSectionCollapsed(prev => ({ ...prev, [name]: !prev[name] }));
  };

  // Build section groups using KNOWN_TAGS only — unknown tags stay in Personal.
  const publicConvs = allConvs.filter(c => c.public);
  const knownTagConvs: Record<string, Conversation[]> = Object.fromEntries(
    KNOWN_TAGS.map(t => [
      t.name,
      allConvs.filter(c => !c.public && (c.tags ?? []).includes(t.name)),
    ])
  );
  // Personal = ALL conversations owned by this user (even if they also appear in Public)
  // that do not have special KNOWN_TAGS.
  const knownTagNames = new Set(KNOWN_TAGS.map(t => t.name));
  const personalConvs = allConvs.filter(c =>
    c.user_id === userId && !(c.tags ?? []).some(tag => knownTagNames.has(tag))
  );

  // Legacy time-group inside Personal
  const grouped: Record<string, Conversation[]> = {};
  for (const conv of personalConvs) {
    const g = getGroup(conv.last_update_time);
    if (!grouped[g]) grouped[g] = [];
    grouped[g].push(conv);
  }

  return (
    <aside
      className={`flex flex-col h-full transition-all duration-300 flex-shrink-0 ${
        collapsed ? "w-14" : "w-64"
      } ${
        isDark
          ? "bg-[#161b22] text-gray-300"
          : "bg-white text-gray-700"
      }`}
    >
      {/* Header — matched to main header height */}
      <div className="flex items-center justify-between px-3 h-[57px] flex-shrink-0">
        {!collapsed && (
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#0071CE] to-[#005baa] flex items-center justify-center text-sm leading-none shadow-sm flex-shrink-0">
              🛡️
            </div>
            <div className="min-w-0">
              <p className={`text-sm font-semibold truncate ${isDark ? "text-gray-100" : "text-gray-800"}`}>SRE Super Agent</p>
              <p className={`text-[10px] ${isDark ? "text-gray-500" : "text-gray-400"}`}>MCP Protocol</p>
            </div>
          </div>
        )}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className={`ml-auto p-1.5 rounded-lg transition-colors ${
            isDark
              ? "hover:bg-[#161b22] text-gray-500 hover:text-gray-300"
              : "hover:bg-gray-100 text-gray-400 hover:text-gray-600"
          }`}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* New Chat Button */}
      <div className="px-2 pt-3 pb-2">
        <button
          onClick={onNewChat}
          className={`flex items-center gap-2.5 w-full px-3 py-2.5 rounded-xl bg-gradient-to-r from-[#0071CE] to-[#005baa] hover:brightness-110 text-white text-sm font-medium transition-all shadow-sm ${
            collapsed ? "justify-center" : ""
          }`}
          title="New chat"
        >
          <MessageSquarePlus className="w-4 h-4 flex-shrink-0" />
          {!collapsed && <span>New chat</span>}
        </button>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto px-2 pb-4">
        {loading && !collapsed && (
          <div className="flex flex-1 items-center justify-center py-10">
            <div className="flex flex-col items-center gap-3">
              <div className="w-6 h-6 rounded-full border-2 border-[#0071CE] border-t-transparent animate-spin" />
              <p className="text-xs text-gray-500">Loading chats…</p>
            </div>
          </div>
        )}

        {!loading && conversations.length === 0 && !collapsed && (
          <div className="flex flex-col items-center justify-center py-10 px-3 text-center">
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-3 ${isDark ? "bg-[#161b22]" : "bg-gray-100"}`}>
              <MessageSquare className={`w-5 h-5 ${isDark ? "text-gray-600" : "text-gray-400"}`} />
            </div>
            <p className={`text-xs leading-relaxed ${isDark ? "text-gray-500" : "text-gray-400"}`}>
              No conversations yet.<br />Start a new chat!
            </p>
          </div>
        )}

        {/* ── Conversation item renderer ─────────────────────────── */}
        {!loading && (() => {
          const ConvItem = ({ conv }: { conv: Conversation }) => {
            const isActive = conv.session_id === activeSessionId;
            return (
              <button
                key={conv.session_id}
                onClick={() => onSelectConversation(conv.session_id)}
                title={conv.title}
                className={`relative flex items-start gap-2.5 w-full px-2.5 py-2.5 rounded-lg text-left transition-all group ${
                  isActive
                    ? isDark ? "bg-[#0071CE]/15 text-white" : "bg-blue-50 text-gray-900"
                    : isDark ? "text-gray-400 hover:bg-[#161b22] hover:text-gray-200"
                           : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                } ${collapsed ? "justify-center" : ""}`}
              >
                {isActive && !collapsed && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-[#0071CE] rounded-r-full" />
                )}
                <div className="relative">
                  {conv.public ? (
                    <Globe className={`w-3.5 h-3.5 flex-shrink-0 mt-0.5 ${isActive ? "text-[#0071CE]" : isDark ? "text-blue-400 group-hover:text-blue-300" : "text-blue-500 group-hover:text-blue-600"}`} />
                  ) : (
                    <Lock className={`w-3.5 h-3.5 flex-shrink-0 mt-0.5 ${isActive ? "text-[#0071CE]" : isDark ? "text-gray-600 group-hover:text-gray-400" : "text-gray-400 group-hover:text-gray-500"}`} />
                  )}
                  {activeMonitors.has(conv.session_id) && (
                    <span 
                      className="absolute -top-1 -right-1.5 w-2 h-2 rounded-full bg-green-500 animate-pulse border border-white dark:border-[#161b22]" 
                      title="Actively monitoring alert"
                    />
                  )}
                </div>
                {!collapsed && (
                  <div className="flex-1 min-w-0 flex items-start justify-between gap-1">
                    <div className="min-w-0">
                        <div className="flex items-center gap-1.5 w-full min-w-0">
                          <p className={`text-xs font-medium truncate flex-1 ${isActive ? isDark ? "text-gray-100" : "text-gray-900" : ""}`}>
                            {conv.shared_by && <span className="mr-1">🔗</span>}
                            {conv.title}
                          </p>

                        </div>
                      <p className={`text-[10px] mt-0.5 ${isDark ? "text-gray-600" : "text-gray-400"}`}>
                        {conv.shared_by
                          ? `${timeAgo(conv.last_update_time)} · by ${conv.shared_by.split("@")[0]}`
                          : timeAgo(conv.last_update_time)}
                      </p>
                    </div>
                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      {/* Known tag toggles (Alert etc.) — only for own sessions */}
                      {!conv.shared_by && KNOWN_TAGS.map(t => {
                        const hasTag = (conv.tags ?? []).includes(t.name);
                        return (
                          <div
                            key={t.name}
                            role="button" tabIndex={0}
                            onClick={(e) => toggleTag(conv, t.name, e)}
                            title={hasTag ? `Remove ${t.name} tag` : `Tag as ${t.name}`}
                            className={`p-1 rounded ${isDark ? "hover:bg-[#161b22]" : "hover:bg-gray-200"}`}
                          >
                            {taggedId === conv.session_id
                              ? <Check className="w-3 h-3 text-green-400" />
                              : <span className={`w-3 h-3 flex items-center ${hasTag ? "text-amber-400" : isDark ? "text-gray-500" : "text-gray-400"}`}>{t.icon}</span>
                            }
                          </div>
                        );
                      })}
                      {/* Make Public toggle */}
                      {!conv.shared_by && (
                        <div
                          role="button" tabIndex={0}
                          onClick={(e) => makePublic(conv, e)}
                          title={conv.public ? "Make private" : "Make public"}
                          className={`p-1 rounded ${isDark ? "hover:bg-[#161b22]" : "hover:bg-gray-200"}`}
                        >
                          {madePublicId === conv.session_id
                            ? <Check className="w-3 h-3 text-green-400" />
                            : <Globe className={`w-3 h-3 ${conv.public ? "text-blue-400" : isDark ? "text-gray-500" : "text-gray-400"}`} />
                          }
                        </div>
                      )}
                      {/* Copy link */}
                      <div
                        role="button" tabIndex={0}
                        onClick={(e) => copyLink(conv.session_id, e)}
                        onKeyDown={(e) => { if (e.key === "Enter") copyLink(conv.session_id, e as unknown as React.MouseEvent); }}
                        title="Copy shareable link"
                        className={`p-1 rounded ${isDark ? "hover:bg-[#161b22]" : "hover:bg-gray-200"}`}
                      >
                        {copiedId === conv.session_id
                          ? <Check className="w-3 h-3 text-green-400" />
                          : <Link2 className={`w-3 h-3 ${isDark ? "text-gray-500" : "text-gray-400"}`} />
                        }
                      </div>
                    </div>
                  </div>
                )}
              </button>
            );
          };

          const SectionHeader = ({ name, icon, count, collapsed: sec }: { name: string; icon: React.ReactNode; count: number; collapsed: boolean }) => (
            <button
              onClick={() => toggleSection(name)}
              className={`flex items-center gap-1.5 w-full px-2 py-1.5 rounded-md text-[10px] uppercase tracking-wider font-semibold transition-colors ${isDark ? "hover:bg-[#21262d] text-gray-500" : "hover:bg-gray-100 text-gray-500"}`}
            >
              {sec ? <ChevronRight className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {icon}
              <span>{name}</span>
              <span className="font-normal normal-case ml-auto opacity-60">({count})</span>
            </button>
          );

          return (
            <>
              {/* ── Public section ──────────────────────────── */}
              {publicConvs.length > 0 && !collapsed && (
                <div className="mt-3">
                  <SectionHeader
                    name="Public"
                    icon={<Globe className="w-3 h-3" />}
                    count={publicConvs.length}
                    collapsed={sectionCollapsed["Public"] ?? true}
                  />
                  {!sectionCollapsed["Public"] && (
                    <div className="space-y-0.5 mt-0.5">
                      {publicConvs.map(c => <ConvItem key={c.session_id} conv={c} />)}
                    </div>
                  )}
                </div>
              )}

              {/* ── Known tag sections (Alert, etc.) ─────────── */}
              {!collapsed && KNOWN_TAGS.map(tagDef => {
                const convs = knownTagConvs[tagDef.name] ?? [];
                if (convs.length === 0) return null;
                return (
                  <div key={tagDef.name} className="mt-3">
                    <SectionHeader
                      name={tagDef.name}
                      icon={tagDef.icon}
                      count={convs.length}
                      collapsed={sectionCollapsed[tagDef.name] ?? true}
                    />
                    {!sectionCollapsed[tagDef.name] && (
                      <div className="space-y-0.5 mt-0.5">
                        {convs.map(c => <ConvItem key={c.session_id} conv={c} />)}
                      </div>
                    )}
                  </div>
                );
              })}

              {/* ── Personal (time-grouped) ──────────────────── */}
              {GROUP_ORDER.filter((g) => grouped[g]?.length).map((group) => (
                <div key={group} className="mt-3">
                  {!collapsed && (
                    <SectionHeader
                      name={group}
                      icon={null}
                      count={grouped[group].length}
                      collapsed={sectionCollapsed[group] ?? false}
                    />
                  )}
                  {(!sectionCollapsed[group] || collapsed) && (
                    <div className="space-y-0.5 mt-0.5">
                      {grouped[group].map(c => <ConvItem key={c.session_id} conv={c} />)}
                    </div>
                  )}
                </div>
              ))}
            </>
          );
        })()}
      </div>

      {/* Footer */}
      <div className={`px-2 py-2 space-y-0.5 flex-shrink-0 border-t ${isDark ? "border-[#30363d]" : "border-gray-100"}`}>
        <button
          onClick={() => onHowToClick?.()}
          className={`flex items-center gap-2 w-full px-2.5 py-1.5 rounded-lg transition-colors text-xs ${
            collapsed ? "justify-center" : ""
          } ${
            isDark
              ? "text-gray-400 hover:bg-[#161b22] hover:text-gray-200"
              : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
          }`}
          title="How To guide"
        >
          <BookOpen className="w-3.5 h-3.5 flex-shrink-0" />
          {!collapsed && <span>How To</span>}
        </button>
      </div>
    </aside>
  );
}
