"use client";

import { useEffect, useRef, useState } from "react";
import { X, ChevronDown, ChevronRight, ArrowRight, Loader2, BookOpen, Search, RotateCcw } from "lucide-react";

interface FAQGroup {
  title: string;
  description: string;
  faqs: string[];
}

// Module-level cache — survives panel close/reopen within the same session
let cachedGroups: FAQGroup[] | null = null;

// Exported for testing only — resets the module-level cache between test cases
export const __resetFAQCache = () => { cachedGroups = null; };

function stripHtml(html: string) {
  return html.replace(/<[^>]*>/g, "").trim();
}

function FAQGroupBlock({
  group,
  query,
  onSelect,
}: {
  group: FAQGroup;
  query: string;
  onSelect: (faq: string) => void;
}) {
  const [open, setOpen] = useState(true);

  const filtered = query
    ? group.faqs.filter((f) => f.toLowerCase().includes(query.toLowerCase()))
    : group.faqs;

  if (filtered.length === 0) return null;

  return (
    <div className="border border-gray-700/50 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 w-full px-4 py-3 text-left bg-gray-800/60 hover:bg-gray-800/90 transition-colors"
        aria-expanded={open}
      >
        <div className="flex-1 min-w-0">
          <span className="text-sm font-semibold text-white">{group.title}</span>
          {group.description && (
            <p className="text-xs text-gray-500 mt-0.5 truncate">{stripHtml(group.description)}</p>
          )}
        </div>
        <span className="text-xs text-gray-600 mr-1">{filtered.length}</span>
        {open
          ? <ChevronDown className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
          : <ChevronRight className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
        }
      </button>

      {open && (
        <ul className="px-3 py-2 bg-gray-900/40 space-y-1">
          {filtered.map((faq, i) => (
            <li key={i}>
              <button
                onClick={() => onSelect(faq)}
                className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-left text-xs text-gray-300 hover:bg-[#0071CE]/15 hover:text-white transition-colors group"
              >
                <ArrowRight className="w-3 h-3 text-gray-600 group-hover:text-[#60a5fa] flex-shrink-0" />
                <span className="flex-1">
                  {query ? <Highlighted text={faq} query={query} /> : faq}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Highlighted({ text, query }: { text: string; query: string }) {
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-[#0071CE]/30 text-white rounded px-0.5">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </>
  );
}

interface HowToPanelProps {
  onSelect: (faq: string) => void;
  onClose: () => void;
}

export function HowToPanel({ onSelect, onClose }: HowToPanelProps) {
  const [groups, setGroups] = useState<FAQGroup[]>(cachedGroups ?? []);
  const [loading, setLoading] = useState(!cachedGroups);
  const [error, setError] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  function load() {
    setLoading(true);
    setError(false);
    fetch("/api/faqs")
      .then((r) => r.json())
      .then((data) => {
        const result = Array.isArray(data) ? data : [];
        cachedGroups = result;
        setGroups(result);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!cachedGroups) load();
    // Auto-focus search when panel opens
    setTimeout(() => searchRef.current?.focus(), 50);
  }, []);

  function handleSelect(faq: string) {
    onSelect(faq);
    onClose();
  }

  const totalVisible = groups.reduce(
    (n, g) => n + (query ? g.faqs.filter((f) => f.toLowerCase().includes(query.toLowerCase())).length : g.faqs.length),
    0
  );

  return (
    <>
      {/* Backdrop */}
      <div className="absolute inset-0 z-20 bg-black/20" onClick={onClose} />

      {/* Panel */}
      <div className="absolute right-0 top-0 bottom-0 z-30 w-80 flex flex-col bg-[#0d1117] border-l border-gray-800/60 shadow-2xl">
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-3.5 border-b border-gray-800/60 flex-shrink-0">
          <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-[#0071CE] to-[#004fa3] flex items-center justify-center">
            <BookOpen className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-sm font-semibold text-gray-100 flex-1">How To</span>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-gray-500 hover:text-gray-200 hover:bg-gray-800 transition-colors"
            title="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Search */}
        <div className="px-3 py-2.5 border-b border-gray-800/40 flex-shrink-0">
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-800/60 border border-gray-700/40 focus-within:border-[#0071CE]/50">
            <Search className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search prompts…"
              className="flex-1 bg-transparent text-xs text-gray-200 placeholder-gray-600 focus:outline-none"
            />
            {query && (
              <button onClick={() => setQuery("")} className="text-gray-600 hover:text-gray-300">
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
          {query && !loading && (
            <p className="text-[10px] text-gray-600 mt-1.5 px-1">{totalVisible} result{totalVisible !== 1 ? "s" : ""}</p>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2.5">
          {loading && (
            <div className="flex items-center justify-center py-16 text-gray-600">
              <Loader2 className="w-4 h-4 animate-spin mr-2" />
              <span className="text-sm">Loading…</span>
            </div>
          )}

          {error && (
            <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
              <p className="text-sm text-gray-500">Could not load FAQs.</p>
              <button
                onClick={load}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-300 border border-gray-700 rounded-lg hover:bg-gray-800 transition-colors"
              >
                <RotateCcw className="w-3 h-3" /> Retry
              </button>
            </div>
          )}

          {!loading && !error && totalVisible === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center text-gray-600">
              <BookOpen className="w-8 h-8 mb-2 opacity-30" />
              <p className="text-sm">{query ? "No prompts match your search." : "No FAQs available."}</p>
            </div>
          )}

          {!loading && !error && groups.map((group, i) => (
            <FAQGroupBlock key={i} group={group} query={query} onSelect={handleSelect} />
          ))}
        </div>

        <div className="px-4 py-2.5 border-t border-gray-800/40 flex-shrink-0">
          <p className="text-[10px] text-gray-700 text-center">Click a prompt to fill the chat input</p>
        </div>
      </div>
    </>
  );
}
