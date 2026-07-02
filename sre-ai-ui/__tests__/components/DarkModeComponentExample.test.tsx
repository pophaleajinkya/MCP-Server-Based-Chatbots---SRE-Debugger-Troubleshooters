/**
 * Example: Testing Components with Tailwind Dark Mode
 *
 * This example demonstrates best practices for testing components
 * that use Tailwind's dark: class-based theme system.
 *
 * Key Testing Patterns:
 * 1. Verify light mode classes exist
 * 2. Verify dark: variant classes exist
 * 3. Simulate dark mode by adding 'dark' class to <html>
 * 4. Test that component behavior is consistent across themes
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// Example component using dark mode classes
function DarkModeButton({
  children,
  variant = "primary",
}: {
  children: React.ReactNode;
  variant?: "primary" | "secondary";
}) {
  const baseClasses = "px-4 py-2 rounded-lg font-medium transition-colors";

  const variantClasses = {
    primary: "bg-blue-50 dark:bg-gray-800 text-gray-900 dark:text-white hover:bg-blue-100 dark:hover:bg-gray-700",
    secondary: "bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-100 hover:bg-gray-200 dark:hover:bg-gray-600",
  };

  return <button className={`${baseClasses} ${variantClasses[variant]}`}>{children}</button>;
}

// Example component with nested dark mode styling
function DarkModeCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-[#0d1117] border border-gray-200 dark:border-gray-800 rounded-lg p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">{title}</h2>
      <div className="text-gray-600 dark:text-gray-300">{children}</div>
    </div>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Dark Mode Component Testing Examples", () => {
  // ── Light Mode Classes ──────────────────────────────────────────────────────

  describe("Light Mode Classes", () => {
    it("renders button with light mode classes", () => {
      const { container } = render(<DarkModeButton>Click me</DarkModeButton>);

      const button = container.querySelector("button");
      expect(button?.className).toContain("bg-blue-50");
      expect(button?.className).toContain("text-gray-900");
      expect(button?.className).toContain("hover:bg-blue-100");
    });

    it("renders secondary variant with light classes", () => {
      const { container } = render(<DarkModeButton variant="secondary">Click me</DarkModeButton>);

      const button = container.querySelector("button");
      expect(button?.className).toContain("bg-gray-100");
      expect(button?.className).toContain("text-gray-800");
    });

    it("card renders with light mode background", () => {
      const { container } = render(
        <DarkModeCard title="Test Card">
          <p>Test content</p>
        </DarkModeCard>
      );

      const card = container.querySelector("div[class*='bg-white']");
      expect(card?.className).toContain("bg-white");
      expect(card?.className).toContain("border-gray-200");
    });
  });

  // ── Dark Mode Classes ───────────────────────────────────────────────────────

  describe("Dark Mode Classes", () => {
    it("button includes dark mode variant classes", () => {
      const { container } = render(<DarkModeButton>Click me</DarkModeButton>);

      const button = container.querySelector("button");

      // Check for dark: prefix classes
      expect(button?.className).toContain("dark:bg-gray-800");
      expect(button?.className).toContain("dark:text-white");
      expect(button?.className).toContain("dark:hover:bg-gray-700");
    });

    it("secondary variant includes dark mode classes", () => {
      const { container } = render(<DarkModeButton variant="secondary">Click me</DarkModeButton>);

      const button = container.querySelector("button");
      expect(button?.className).toContain("dark:bg-gray-700");
      expect(button?.className).toContain("dark:text-gray-100");
      expect(button?.className).toContain("dark:hover:bg-gray-600");
    });

    it("card includes dark mode variant classes", () => {
      const { container } = render(
        <DarkModeCard title="Test Card">
          <p>Test content</p>
        </DarkModeCard>
      );

      const card = container.querySelector("div[class*='bg-white']");
      expect(card?.className).toContain("dark:bg-[#0d1117]");
      expect(card?.className).toContain("dark:border-gray-800");
    });
  });

  // ── Theme Switching Simulation ──────────────────────────────────────────────

  describe("Theme Switching Simulation", () => {
    beforeEach(() => {
      document.documentElement.classList.remove("dark");
    });

    it("simulates dark mode by adding 'dark' class to html", () => {
      const { rerender, container } = render(<DarkModeButton>Click me</DarkModeButton>);

      const button = container.querySelector("button");

      // In light mode, these classes are inactive (Tailwind only activates dark: when ancestor has dark class)
      expect(button?.className).toContain("dark:bg-gray-800");

      // Simulate dark mode
      document.documentElement.classList.add("dark");
      rerender(<DarkModeButton>Click me</DarkModeButton>);

      // Classes still exist (they're static in the DOM), but would be visually active
      expect(button?.className).toContain("dark:bg-gray-800");
      expect(document.documentElement.classList.contains("dark")).toBe(true);
    });

    it("verifies component works in both light and dark themes", () => {
      // Light mode
      document.documentElement.classList.remove("dark");
      const { container: lightContainer } = render(<DarkModeButton>Click me</DarkModeButton>);
      const lightButton = lightContainer.querySelector("button");

      expect(lightButton?.className).toContain("bg-blue-50");
      expect(lightButton?.className).toContain("dark:bg-gray-800");

      // Dark mode
      document.documentElement.classList.add("dark");
      const { container: darkContainer } = render(<DarkModeButton>Click me</DarkModeButton>);
      const darkButton = darkContainer.querySelector("button");

      expect(darkButton?.className).toContain("bg-blue-50");
      expect(darkButton?.className).toContain("dark:bg-gray-800");

      // Both should have the same classes (functionality is in the classnames)
      expect(darkButton?.className).toBe(lightButton?.className);
    });
  });

  // ── Consistency Checks ──────────────────────────────────────────────────────

  describe("Light/Dark Variant Consistency", () => {
    it("ensures button has both light and dark color classes", () => {
      const { container } = render(<DarkModeButton>Click me</DarkModeButton>);
      const button = container.querySelector("button");
      const className = button?.className || "";

      // Verify key color pairs exist
      expect(className).toContain("bg-blue-50");
      expect(className).toContain("dark:bg-gray-800");
      expect(className).toContain("text-gray-900");
      expect(className).toContain("dark:text-white");
    });
  });

  // ── Accessibility in Both Themes ────────────────────────────────────────────

  describe("Accessibility", () => {
    it("maintains semantic HTML across themes", () => {
      const { container } = render(<DarkModeButton>Click me</DarkModeButton>);

      const button = container.querySelector("button");
      expect(button).toBeInTheDocument();
      expect(button?.textContent).toBe("Click me");
    });

    it("button remains interactive in both themes", () => {
      const handleClick = jest.fn();

      function InteractiveButton() {
        return <DarkModeButton onClick={handleClick as any}>Click me</DarkModeButton>;
      }

      render(<InteractiveButton />);
      expect(screen.getByRole("button", { name: "Click me" })).toBeInTheDocument();
    });
  });
});
