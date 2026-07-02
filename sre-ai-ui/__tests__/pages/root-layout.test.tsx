jest.mock("next/font/google", () => ({
  Inter: () => ({ variable: "--font-sans", className: "inter" }),
  JetBrains_Mono: () => ({ variable: "--font-mono", className: "mono" }),
}));

jest.mock("@/contexts/AuthContext", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => {
    const React = require("react");
    return React.createElement("div", { "data-testid": "auth-provider" }, children);
  },
  useAuth: jest.fn(),
}));

import React from "react";
import { render, screen } from "@testing-library/react";
import RootLayout from "@/app/layout";

describe("RootLayout", () => {
  it("renders children inside the layout", () => {
    render(
      <RootLayout>
        <div data-testid="child">Hello</div>
      </RootLayout>
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });

  it("wraps children in AuthProvider", () => {
    render(
      <RootLayout>
        <div data-testid="child">Hello</div>
      </RootLayout>
    );
    expect(screen.getByTestId("auth-provider")).toBeInTheDocument();
  });

  it("passes children through to AuthProvider", () => {
    render(
      <RootLayout>
        <div data-testid="child">Hello</div>
      </RootLayout>
    );
    const authProvider = screen.getByTestId("auth-provider");
    expect(authProvider).toHaveTextContent("Hello");
  });
});
