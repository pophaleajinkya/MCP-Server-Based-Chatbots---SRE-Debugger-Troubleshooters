"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, BookOpen, ChevronDown, ChevronRight, Loader2, RotateCcw } from "lucide-react";
import { CopyButton } from "@/components/CopyButton";

function stripHtml(html: string) {
  return html.replace(/<[^>]*>/g, "").trim();
}

interface FAQGroup {
  title: string;
  description: string;
  faqs: string[];
}

function FAQGroupBlock({ group }: { group: FAQGroup }) {
  const [open, setOpen] = useState(true);

  return (
    <div className="rounded-2xl border border-gray-700/50 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-3 w-full px-5 py-4 text-left bg-gray-800/60 hover:bg-gray-800/90 transition-colors"
        aria-expanded={open}
      >
        <div className="flex-1 min-w-0">
          <span className="text-base font-semibold text-white">{group.title}</span>
          {group.description && (
            <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">{stripHtml(group.description)}</p>
          )}
        </div>
        <span className="text-xs text-gray-600 mr-2 flex-shrink-0">{group.faqs.length} prompts</span>
        {open
          ? <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" />
          : <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
        }
      </button>

      {open && (
        <ul className="px-4 py-3 bg-gray-900/40 space-y-1.5">
          {group.faqs.map((faq, i) => (
            <li
              key={i}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-gray-800/40 hover:bg-gray-800/70 transition-colors group"
            >
              <span className="text-xs text-gray-600 font-mono w-5 flex-shrink-0">{i + 1}.</span>
              <span className="text-sm text-gray-200 flex-1">{faq}</span>
              <CopyButton text={faq} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function HowToPage() {
  const [groups, setGroups] = useState<FAQGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  function load() {
    setLoading(true);
    setError(false);
    fetch("/api/faqs")
      .then((r) => r.json())
      .then((data) => setGroups(Array.isArray(data) ? data : []))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  const totalPrompts = groups.reduce((n, g) => n + g.faqs.length, 0);

  return (
    <div className="min-h-screen bg-[#0d1117] text-gray-100">
      <header className="sticky top-0 z-10 flex items-center gap-3 px-6 py-4 bg-[#0d1117]/95 backdrop-blur border-b border-gray-800/60">
        <Link
          href="/"
          className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to chat
        </Link>
        <span className="text-gray-700">|</span>
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-[#0071CE] to-[#004fa3] flex items-center justify-center">
            <BookOpen className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-sm font-semibold text-gray-200">How To</span>
        </div>
        {!loading && !error && (
          <span className="ml-auto text-xs text-gray-700">{groups.length} agents · {totalPrompts} prompts</span>
        )}
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-white">How To Guide</h1>
          <p className="mt-1.5 text-sm text-gray-400">
            Reference prompts for each agent. Click a prompt to copy it into your chat.
          </p>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-20 text-gray-500">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            <span className="text-sm">Loading…</span>
          </div>
        )}

        {error && (
          <div className="flex flex-col items-center justify-center py-20 text-center gap-3 text-gray-600">
            <p className="text-sm">Could not load FAQs from the backend.</p>
            <button
              onClick={load}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-300 border border-gray-700 rounded-lg hover:bg-gray-800 transition-colors"
            >
              <RotateCcw className="w-3 h-3" /> Retry
            </button>
          </div>
        )}

        {!loading && !error && groups.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-center text-gray-600">
            <BookOpen className="w-10 h-10 mb-3 opacity-30" />
            <p className="text-sm">No FAQ groups returned by the backend.</p>
          </div>
        )}

        {!loading && !error && groups.map((group, i) => (
          <FAQGroupBlock key={i} group={group} />
        ))}
      </main>
    </div>
  );
}
