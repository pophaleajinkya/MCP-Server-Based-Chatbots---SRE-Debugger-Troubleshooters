import "@testing-library/jest-dom";

// jsdom doesn't implement matchMedia — provide a minimal stub (browser env only)
if (typeof window !== "undefined") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: jest.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: jest.fn(),
      removeListener: jest.fn(),
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      dispatchEvent: jest.fn(),
    })),
  });
}

// Polyfill Web Streams API for jsdom (needed for hook tests that mock fetch with ReadableStream)
if (typeof ReadableStream === "undefined") {
  const { ReadableStream, TransformStream, WritableStream } = require("stream/web");
  Object.assign(global, { ReadableStream, TransformStream, WritableStream });
}
if (typeof TextEncoder === "undefined") {
  const { TextEncoder, TextDecoder } = require("util");
  Object.assign(global, { TextEncoder, TextDecoder });
}

// Mock next/navigation globally
jest.mock("next/navigation", () => ({
  useRouter: jest.fn(() => ({
    push: jest.fn(),
    replace: jest.fn(),
    refresh: jest.fn(),
    back: jest.fn(),
  })),
  useSearchParams: jest.fn(() => new URLSearchParams()),
  usePathname: jest.fn(() => "/"),
  redirect: jest.fn(),
}));

// Mock next/headers globally
jest.mock("next/headers", () => ({
  cookies: jest.fn(() => ({
    get: jest.fn(),
    set: jest.fn(),
    delete: jest.fn(),
  })),
  headers: jest.fn(() => ({
    get: jest.fn(),
  })),
}));

// ─── CopilotKit mocks (shared across all component tests) ────────────────────
// Using a mutable state object so tests can control messages/isLoading/etc.
const _copilotKitState = {
  messages: [] as unknown[],
  isLoading: false,
  sendMessage: jest.fn(),
  stopGeneration: jest.fn(),
  setMessages: jest.fn(),
};

jest.mock("@copilotkit/react-core", () => {
  const React = require("react");
  return {
    __esModule: true,
    __copilotKitMockState: _copilotKitState,
    CopilotKit: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
    useCopilotChatInternal: () => _copilotKitState,
  };
});

jest.mock("@copilotkit/runtime-client-gql", () => ({
  TextMessage: jest.fn().mockImplementation((args: Record<string, unknown>) => ({
    ...args,
    isTextMessage: () => true,
    isActionExecutionMessage: () => false,
    isResultMessage: () => false,
    isAgentStateMessage: () => false,
    isImageMessage: () => false,
  })),
  ActionExecutionMessage: jest.fn().mockImplementation((args: Record<string, unknown>) => ({
    ...args,
    isTextMessage: () => false,
    isActionExecutionMessage: () => true,
    isResultMessage: () => false,
    isAgentStateMessage: () => false,
    isImageMessage: () => false,
  })),
  MessageRole: { User: "user", Assistant: "assistant" },
}));

jest.mock("@copilotkit/runtime", () => ({
  CopilotRuntime: jest.fn().mockImplementation(() => ({})),
  copilotRuntimeNextJSAppRouterEndpoint: jest.fn().mockReturnValue({
    handleRequest: jest.fn().mockResolvedValue(new Response("ok")),
  }),
}));

// ─── react-markdown mock (ESM-only module; ts-jest cannot parse it) ──────────
jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({
    children,
    components,
  }: {
    children: string;
    remarkPlugins?: unknown[];
    components?: Record<string, unknown>;
  }) => {
    const React = require("react");
    if (typeof children !== "string")
      return React.createElement("div", null, children);

    let key = 0;

    /** Parse inline bold/italic/link patterns into React nodes. */
    function parseInline(text: string): React.ReactNode {
      const inlineRegex = /(\*\*(.+?)\*\*|_(.+?)_|\[([^\]]+)\]\(([^)]+)\))/g;
      const nodes: React.ReactNode[] = [];
      let lastIdx = 0;
      let m: RegExpExecArray | null;

      while ((m = inlineRegex.exec(text)) !== null) {
        const before = text.slice(lastIdx, m.index);
        if (before) nodes.push(before);

        if (m[0].startsWith("**")) {
          const StrongComp = components?.strong as
            | ((p: { children: React.ReactNode }) => React.ReactNode)
            | undefined;
          nodes.push(
            StrongComp
              ? React.createElement(StrongComp as React.FC<{ children: React.ReactNode }>, { key: key++ }, m[2])
              : React.createElement("strong", { key: key++ }, m[2])
          );
        } else if (m[0].startsWith("_")) {
          nodes.push(React.createElement("em", { key: key++ }, m[3]));
        } else {
          // link [text](url)
          const AComp = components?.a as
            | ((p: { href: string; children: React.ReactNode }) => React.ReactNode)
            | undefined;
          nodes.push(
            AComp
              ? React.createElement(
                  AComp as React.FC<{ href: string; children: React.ReactNode }>,
                  { key: key++, href: m[5] },
                  m[4]
                )
              : React.createElement("a", { key: key++, href: m[5] }, m[4])
          );
        }
        lastIdx = m.index + m[0].length;
      }

      const after = text.slice(lastIdx);
      if (after) nodes.push(after);

      return nodes.length === 1
        ? nodes[0]
        : React.createElement(React.Fragment, { key: key++ }, ...nodes);
    }

    const fenceRegex = /```(\w*)\n([\s\S]*?)```/g;
    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = fenceRegex.exec(children)) !== null) {
      const textBefore = children.slice(lastIndex, match.index).trim();
      if (textBefore)
        parts.push(React.createElement("p", { key: key++ }, parseInline(textBefore)));

      const lang: string = match[1];
      const code: string = match[2];
      const className = lang ? `language-${lang}` : undefined;
      const codeEl = React.createElement("code", { className }, code);

      const PreComp = components?.pre as
        | ((p: { children: React.ReactNode }) => React.ReactNode)
        | undefined;
      if (PreComp) {
        parts.push(
          React.createElement(PreComp as React.FC<{ children: React.ReactNode }>, { key: key++ }, codeEl)
        );
      } else {
        parts.push(React.createElement("pre", { key: key++ }, codeEl));
      }
      lastIndex = match.index + match[0].length;
    }

    const remaining = children.slice(lastIndex).trim();
    if (remaining)
      parts.push(React.createElement("p", { key: key++ }, parseInline(remaining)));

    return React.createElement(React.Fragment, null, ...parts);
  },
}));

jest.mock("remark-gfm", () => ({
  __esModule: true,
  default: jest.fn(),
}));

// ─── Recharts mock (prevents SSR/canvas errors in jsdom) ─────────────────────
jest.mock("recharts", () => {
  const React = require("react");
  const stub =
    (testId?: string) =>
    ({ children, ...props }: { children?: React.ReactNode; [k: string]: unknown }) =>
      React.createElement("div", { "data-testid": testId ?? (props["data-testid"] as string) ?? "recharts-stub" }, children);
  return {
    __esModule: true,
    ResponsiveContainer: stub("recharts-responsive-container"),
    LineChart: stub("recharts-line-chart"),
    BarChart: stub("recharts-bar-chart"),
    AreaChart: stub("recharts-area-chart"),
    Line: () => null,
    Bar: () => null,
    Area: () => null,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
    Legend: () => null,
  };
});

// Silence console.error in tests unless explicitly needed
const originalConsoleError = console.error;
beforeAll(() => {
  console.error = jest.fn();
});
afterAll(() => {
  console.error = originalConsoleError;
});
