"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Bot, Shield, LogIn } from "lucide-react";

function LoginContent() {
  const searchParams = useSearchParams();
  const error = searchParams.get("error");

  return (
    <main className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Card */}
        <div className="bg-white rounded-2xl shadow-lg border border-gray-100 overflow-hidden">
          {/* Header bar */}
          <div className="h-1.5 bg-gradient-to-r from-[#0071CE] to-[#004fa3]" />

          <div className="px-8 py-10">
            {/* Logo */}
            <div className="flex flex-col items-center mb-8">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[#0071CE] to-[#004fa3] flex items-center justify-center shadow-md mb-4">
                <Bot className="w-8 h-8 text-white" />
              </div>
              <h1 className="text-2xl font-bold text-gray-900">SreAI</h1>
              <p className="text-sm text-gray-500 mt-1">Intelligent interface for ADK-powered agents</p>
            </div>

            {/* Error */}
            {error && (
              <div className="mb-6 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                <strong>Authentication error:</strong>{" "}
                {decodeURIComponent(error)}
              </div>
            )}

            {/* SSO info */}
            <div className="flex items-start gap-3 mb-6 px-4 py-3 bg-blue-50 border border-blue-100 rounded-xl text-sm text-blue-700">
              <Shield className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>
                This app is protected by <strong>Walmart PingFederate SSO</strong>. Sign in with your Walmart credentials.
              </span>
            </div>

            {/* Login button */}
            <a
              href="/api/auth/login"
              className="flex items-center justify-center gap-2.5 w-full px-4 py-3 rounded-xl bg-gradient-to-r from-[#0071CE] to-[#004fa3] hover:brightness-110 text-white font-semibold text-sm transition-all shadow-sm"
            >
              <LogIn className="w-4 h-4" />
              Sign in with Walmart SSO
            </a>
          </div>

          {/* Footer */}
          <div className="px-8 py-4 bg-gray-50 border-t border-gray-100">
            <p className="text-[11px] text-gray-400 text-center">
              For access issues, contact your IT administrator.
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginContent />
    </Suspense>
  );
}
