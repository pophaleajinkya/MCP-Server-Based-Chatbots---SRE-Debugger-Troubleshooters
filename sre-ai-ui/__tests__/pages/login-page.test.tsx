/**
 * Tests for src/app/login/page.tsx
 *
 * Covers:
 *  - Renders app title
 *  - Renders sign-in link and its href
 *  - Shows PingFederate SSO message
 *  - Does not show error when no error param
 *  - Shows decoded error message when error param is present
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { useSearchParams } from "next/navigation";

import LoginPage from "@/app/login/page";

describe("LoginPage", () => {
  // The global mock from jest.setup.ts returns new URLSearchParams() (no params),
  // which is the "no error" default for most tests.

  afterEach(() => {
    jest.clearAllMocks();
  });

  it("renders the app title 'SreAI'", () => {
    render(<LoginPage />);
    expect(screen.getByRole("heading", { name: /SreAI/i })).toBeInTheDocument();
  });

  it("renders the 'Sign in with Walmart SSO' link", () => {
    render(<LoginPage />);
    expect(
      screen.getByRole("link", { name: /Sign in with Walmart SSO/i })
    ).toBeInTheDocument();
  });

  it("the sign-in link points to /api/auth/login", () => {
    render(<LoginPage />);
    const link = screen.getByRole("link", { name: /Sign in with Walmart SSO/i });
    expect(link).toHaveAttribute("href", "/api/auth/login");
  });

  it("shows the PingFederate SSO message", () => {
    render(<LoginPage />);
    expect(screen.getByText(/Walmart PingFederate SSO/i)).toBeInTheDocument();
  });

  it("does NOT show an error message when no error param is present", () => {
    render(<LoginPage />);
    expect(screen.queryByText(/Authentication error/i)).not.toBeInTheDocument();
  });

  it("shows an error message when the 'error' query param is set", () => {
    (useSearchParams as jest.Mock).mockReturnValueOnce(
      new URLSearchParams("error=auth_failed")
    );

    render(<LoginPage />);

    expect(screen.getByText(/Authentication error/i)).toBeInTheDocument();
    expect(screen.getByText(/auth_failed/i)).toBeInTheDocument();
  });

  it("decodes a URL-encoded error value in the error message", () => {
    (useSearchParams as jest.Mock).mockReturnValueOnce(
      new URLSearchParams("error=invalid%20credentials")
    );

    render(<LoginPage />);

    // decodeURIComponent turns "invalid%20credentials" → "invalid credentials"
    expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
  });
});
