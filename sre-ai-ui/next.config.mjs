/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  // Pin the workspace root so Next.js doesn't pick up the stray
  // /Users/m0c00jt/git/package-lock.json and infer the wrong root.
  // See https://nextjs.org/docs/app/api-reference/config/next-config-js/output#caveats
  outputFileTracingRoot: new URL(".", import.meta.url).pathname,
  // Transpile mermaid v11 via SWC so webpack bundles it inline instead of
  // splitting mermaid.core.mjs into a separate chunk (which causes ChunkLoadError).
  transpilePackages: ["mermaid"],
  // Exclude CopilotKit runtime and its transitive deps (graphql-yoga, @whatwg-node/fetch)
  // from webpack bundling — they use dynamic require() that webpack can't statically analyse.
  // Next.js 15: serverComponentsExternalPackages moved out of experimental
  serverExternalPackages: [
    "@copilotkit/runtime",
    "graphql-yoga",
    "@whatwg-node/fetch",
    "@whatwg-node/server",
  ],
  /**
   * Map Kubernetes probe paths → Next.js API routes.
   * kitt.yml probes hit /health, /health/liveness, /health/readiness (no /api prefix).
   * Middleware runs before rewrites, so it sees the original /health/* paths —
   * those are listed in PUBLIC_PATHS to bypass auth.
   */
  async rewrites() {
    const sreApiUrl =
      process.env.SRE_OPERATOR_URL ||
      "http://localhost:9099";
    return [
      { source: "/health", destination: "/api/health" },
      { source: "/health/liveness", destination: "/api/health/liveness" },
      { source: "/health/readiness", destination: "/api/health/readiness" },
      {
        source: "/sre-api/:path*",
        destination: `${sreApiUrl}/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/api/:path*",
        headers: [
          { key: "Access-Control-Allow-Origin", value: "*" },
          { key: "Access-Control-Allow-Methods", value: "GET, POST, OPTIONS" },
          { key: "Access-Control-Allow-Headers", value: "Content-Type" },
        ],
      },
    ];
  },
};

export default nextConfig;
