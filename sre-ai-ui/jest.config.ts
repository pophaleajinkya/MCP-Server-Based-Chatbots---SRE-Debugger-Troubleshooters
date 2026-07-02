// Ensure React loads its development build (which includes `act`) even if
// NODE_ENV=production is inherited from the CI environment.
// Cast bypasses TypeScript's readonly constraint on NODE_ENV.
(process.env as Record<string, string>)["NODE_ENV"] = "test";

import nextJest from "next/jest.js";
import type { Config } from "jest";

const createJestConfig = nextJest({ dir: "./" });

const customJestConfig: Config = {
  maxWorkers: 4,
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  testMatch: [
    "**/__tests__/**/*.test.+(ts|tsx|js)",
    "**/__tests__/**/*.spec.+(ts|tsx|js)",
  ],
  testPathIgnorePatterns: ["/.next/", "/node_modules/", "/e2e/"],
  preset: "ts-jest",
  transform: {
    "^.+\\.(js|jsx|ts|tsx)$": [
      "ts-jest",
      {
        tsconfig: {
          jsx: "react-jsx",
        },
      },
    ],
  },
  moduleNameMapper: {
    "\\.(css|less|scss|sass)$": "identity-obj-proxy",
    "\\.(png|jpg|jpeg|gif|svg|ico)$": "<rootDir>/__mocks__/fileMock.ts",
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  collectCoverage: true,
  coverageDirectory: "coverage",
  coverageReporters: ["lcov", "text", "text-summary"],
  coverageProvider: "v8",
  collectCoverageFrom: [
    "src/lib/**/*.ts",
    "src/contexts/**/*.tsx",
    "src/components/**/*.tsx",
    "src/hooks/**/*.ts",
    "src/middleware.ts",
    "src/instrumentation.ts",
    "src/app/api/**/*.ts",
    "src/app/page.tsx",
    "src/app/layout.tsx",
    "src/app/login/page.tsx",
    "src/app/dev/charts/page.tsx",
    "src/app/howto/page.tsx",
    "!src/**/*.d.ts",
  ],
  testEnvironment: "jest-environment-jsdom",
  reporters: [
    "default",
    [
      "jest-sonar",
      {
        outputDirectory: ".",
        reportFile: "sonar-report.xml",
      },
    ],
    "@walmartlabs/jest-reporter-testburst",
  ],
};

export default createJestConfig(customJestConfig);
