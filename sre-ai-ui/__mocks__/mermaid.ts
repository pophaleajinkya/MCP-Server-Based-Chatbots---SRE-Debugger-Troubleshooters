// Manual mock for the ESM-only "mermaid" package.
// Jest auto-uses this file for both static and dynamic `import("mermaid")` calls
// because it lives at <rootDir>/__mocks__/mermaid.ts (root-level __mocks__ for
// node_modules packages).
//
// Tests that need to control behaviour can import this module and reconfigure
// the jest.fn() instances directly.

const mermaid = {
  initialize: jest.fn(),
  parse: jest.fn().mockResolvedValue(true),
  render: jest.fn().mockResolvedValue({ svg: "<svg>test diagram</svg>" }),
};

export default mermaid;
