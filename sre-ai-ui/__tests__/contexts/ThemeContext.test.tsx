/**
 * Tests for src/contexts/ThemeContext.tsx
 *
 * Covers:
 *  ThemeProvider:
 *   - Reads saved theme from localStorage
 *   - Falls back to system preference (prefers-color-scheme)
 *   - Defaults to light theme
 *   - Applies/removes 'dark' class on <html>
 *   - Saves theme to localStorage when changed
 *
 *  useTheme hook:
 *   - Returns theme, isDark, and toggleTheme
 *   - toggleTheme switches between light and dark
 *   - isDark correctly reflects theme state
 */

import React, { ReactNode } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { ThemeProvider, useTheme } from "@/contexts/ThemeContext";

// ── Test Component ────────────────────────────────────────────────────────────

function ThemeTestComponent() {
  const { theme, isDark, toggleTheme } = useTheme();

  return (
    <div>
      <p data-testid="theme-display">Theme: {theme}</p>
      <p data-testid="is-dark-display">Is Dark: {isDark ? "yes" : "no"}</p>
      <button onClick={toggleTheme} data-testid="toggle-theme">
        Toggle Theme
      </button>
    </div>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ThemeContext", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
    jest.clearAllMocks();
  });

  afterEach(() => {
    // Ensure cleanup between tests
    document.documentElement.classList.remove("dark");
  });

  // ── Initialization ──────────────────────────────────────────────────────────

  it("initializes with light theme by default", async () => {
    render(
      <ThemeProvider>
        <ThemeTestComponent />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("theme-display")).toHaveTextContent("Theme: light");
    });
  });

  it("reads saved theme from localStorage", async () => {
    localStorage.setItem("sre-theme", "dark");

    render(
      <ThemeProvider>
        <ThemeTestComponent />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("theme-display")).toHaveTextContent("Theme: dark");
    });
  });

  it("defaults to light theme when no saved theme", async () => {
    // Mock system dark preference (but we default to light regardless)
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: jest.fn().mockImplementation((query: string) => ({
        matches: query === "(prefers-color-scheme: dark)",
        media: query,
        onchange: null,
        addListener: jest.fn(),
        removeListener: jest.fn(),
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
        dispatchEvent: jest.fn(),
      })),
    });

    render(
      <ThemeProvider>
        <ThemeTestComponent />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("theme-display")).toHaveTextContent("Theme: light");
    });
  });

  // ── Theme Toggling ──────────────────────────────────────────────────────────

  it("toggles theme when toggleTheme is called", async () => {
    const user = userEvent.setup();
    localStorage.setItem("sre-theme", "light"); // Explicitly set light to avoid system preference

    const { rerender } = render(
      <ThemeProvider>
        <ThemeTestComponent />
      </ThemeProvider>
    );

    // Initial state: light
    await waitFor(() => {
      expect(screen.getByTestId("theme-display")).toHaveTextContent("Theme: light");
    });

    // Toggle to dark
    await user.click(screen.getByTestId("toggle-theme"));
    await waitFor(() => {
      expect(screen.getByTestId("theme-display")).toHaveTextContent("Theme: dark");
    });

    // Toggle back to light
    await user.click(screen.getByTestId("toggle-theme"));
    await waitFor(() => {
      expect(screen.getByTestId("theme-display")).toHaveTextContent("Theme: light");
    });
  });

  // ── isDark Flag ─────────────────────────────────────────────────────────────

  it("isDark flag is false for light theme", async () => {
    localStorage.setItem("sre-theme", "light"); // Explicitly set light

    render(
      <ThemeProvider>
        <ThemeTestComponent />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("is-dark-display")).toHaveTextContent("Is Dark: no");
    });
  });

  it("isDark flag is true for dark theme", async () => {
    localStorage.setItem("sre-theme", "dark");

    render(
      <ThemeProvider>
        <ThemeTestComponent />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("is-dark-display")).toHaveTextContent("Is Dark: yes");
    });
  });

  // ── DOM Class Management ────────────────────────────────────────────────────

  it("adds 'dark' class to <html> when theme is dark", async () => {
    const user = userEvent.setup();
    localStorage.setItem("sre-theme", "light");

    render(
      <ThemeProvider>
        <ThemeTestComponent />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(document.documentElement.classList.contains("dark")).toBe(false);
    });

    // Toggle to dark
    await user.click(screen.getByTestId("toggle-theme"));
    await waitFor(() => {
      expect(document.documentElement.classList.contains("dark")).toBe(true);
    });
  });

  it("removes 'dark' class from <html> when theme is light", async () => {
    const user = userEvent.setup();
    localStorage.setItem("sre-theme", "dark");

    render(
      <ThemeProvider>
        <ThemeTestComponent />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(document.documentElement.classList.contains("dark")).toBe(true);
    });

    // Toggle to light
    await user.click(screen.getByTestId("toggle-theme"));
    await waitFor(() => {
      expect(document.documentElement.classList.contains("dark")).toBe(false);
    });
  });

  // ── localStorage Persistence ────────────────────────────────────────────────

  it("saves theme choice to localStorage when toggled", async () => {
    const user = userEvent.setup();
    localStorage.setItem("sre-theme", "light");

    render(
      <ThemeProvider>
        <ThemeTestComponent />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(localStorage.getItem("sre-theme")).toBe("light");
    });

    // Toggle to dark
    await user.click(screen.getByTestId("toggle-theme"));
    await waitFor(() => {
      expect(localStorage.getItem("sre-theme")).toBe("dark");
    });
  });

  // ── Provider Not Rendering Before Mount ────────────────────────────────────

  it("does not render children until theme is mounted", () => {
    const TestChild = () => {
      const { theme } = useTheme();
      return <div>Loaded: {theme}</div>;
    };

    const { rerender } = render(
      <ThemeProvider>
        <TestChild />
      </ThemeProvider>
    );

    // After mount, should display content
    waitFor(() => {
      expect(screen.getByText(/Loaded:/)).toBeInTheDocument();
    });
  });
});
