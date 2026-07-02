/**
 * Dark Mode Tests for Sidebar Component
 *
 * These tests verify that the Sidebar component renders the correct classes
 * based on the useTheme() hook (isDark ternary pattern).
 */

import React from "react";
import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { Conversation } from "@/types";

// Mock useAuth so Sidebar can call it without an AuthProvider wrapper
jest.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ logout: jest.fn() }),
}));

// Default to light mode; individual tests override as needed
let mockTheme = "light";
jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ theme: mockTheme }),
}));

import { Sidebar } from "@/components/Sidebar";

// ── Test Data ─────────────────────────────────────────────────────────────────

const NOW = Date.now() / 1000;
const MOCK_CONVERSATIONS: Conversation[] = [
  {
    session_id: "session-1",
    user_id: "testuser",
    title: "Test conversation",
    last_update_time: NOW - 300,
  },
];

const defaultProps = {
  conversations: MOCK_CONVERSATIONS,
  activeSessionId: "session-1",
  userId: "testuser",
  loading: false,
  onNewChat: jest.fn(),
  onSelectConversation: jest.fn(),
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Sidebar - Dark Mode Classes", () => {
  beforeEach(() => {
    mockTheme = "light";
    jest.clearAllMocks();
  });

  // ── Main Container ─────────────────────────────────────────────────────────

  describe("Container Classes", () => {
    it("renders main aside with light mode background", () => {
      const { container } = render(<Sidebar {...defaultProps} />);
      const aside = container.querySelector("aside");

      expect(aside?.className).toContain("bg-white");
      expect(aside?.className).toContain("text-gray-700");
    });

    it("renders main aside with dark mode classes", () => {
      mockTheme = "dark";
      const { container } = render(<Sidebar {...defaultProps} />);
      const aside = container.querySelector("aside");

      expect(aside?.className).toContain("bg-[#161b22]");
      expect(aside?.className).toContain("text-gray-300");
    });
  });

  // ── Header Section ─────────────────────────────────────────────────────────

  describe("Header Classes", () => {
    it("header text has light mode colors", () => {
      const { container } = render(<Sidebar {...defaultProps} />);
      const paragraphs = container.querySelectorAll("p");

      let foundTitle = false;
      paragraphs.forEach((p) => {
        if (p.textContent?.includes("SRE Super Agent")) {
          expect(p.className).toContain("text-gray-800");
          foundTitle = true;
        }
      });
      expect(foundTitle).toBe(true);
    });

    it("header text has dark mode colors", () => {
      mockTheme = "dark";
      const { container } = render(<Sidebar {...defaultProps} />);
      const paragraphs = container.querySelectorAll("p");

      let foundTitle = false;
      paragraphs.forEach((p) => {
        if (p.textContent?.includes("SRE Super Agent")) {
          expect(p.className).toContain("text-gray-100");
          foundTitle = true;
        }
      });
      expect(foundTitle).toBe(true);
    });

    it("header subtitle has proper theme colors", () => {
      const { container } = render(<Sidebar {...defaultProps} />);
      const allParagraphs = container.querySelectorAll("p");

      let foundSubtitle = false;
      allParagraphs.forEach((p) => {
        if (p.textContent?.includes("MCP")) {
          expect(p.className).toContain("text-gray-400");
          foundSubtitle = true;
        }
      });

      expect(foundSubtitle).toBe(true);
    });
  });

  // ── Collapse Button ────────────────────────────────────────────────────────

  describe("Collapse Button Classes", () => {
    it("collapse button has light mode hover states", () => {
      const { container } = render(<Sidebar {...defaultProps} />);

      const buttons = container.querySelectorAll("button");
      let collapseButton: HTMLElement | null = null;

      buttons.forEach((btn) => {
        if (btn.title === "Collapse sidebar") {
          collapseButton = btn;
        }
      });

      if (collapseButton) {
        expect(collapseButton.className).toContain("hover:bg-gray-100");
        expect(collapseButton.className).toContain("text-gray-400");
      }
    });

    it("collapse button has dark mode hover states", () => {
      mockTheme = "dark";
      const { container } = render(<Sidebar {...defaultProps} />);

      const buttons = container.querySelectorAll("button");
      let collapseButton: HTMLElement | null = null;

      buttons.forEach((btn) => {
        if (btn.title === "Collapse sidebar") {
          collapseButton = btn;
        }
      });

      if (collapseButton) {
        expect(collapseButton.className).toContain("hover:bg-[#161b22]");
        expect(collapseButton.className).toContain("text-gray-500");
      }
    });
  });

  // ── Empty State ────────────────────────────────────────────────────────────

  describe("Empty State Classes", () => {
    it("empty state has light mode colors", () => {
      const { container } = render(
        <Sidebar {...defaultProps} loading={false} conversations={[]} />
      );

      const paragraphs = container.querySelectorAll("p");
      let foundEmptyText = false;

      paragraphs.forEach((p) => {
        if (p.textContent?.includes("No conversations")) {
          expect(p.className).toContain("text-gray-400");
          foundEmptyText = true;
        }
      });

      expect(foundEmptyText).toBe(true);
    });

    it("empty state has dark mode colors", () => {
      mockTheme = "dark";
      const { container } = render(
        <Sidebar {...defaultProps} loading={false} conversations={[]} />
      );

      const paragraphs = container.querySelectorAll("p");
      let foundEmptyText = false;

      paragraphs.forEach((p) => {
        if (p.textContent?.includes("No conversations")) {
          expect(p.className).toContain("text-gray-500");
          foundEmptyText = true;
        }
      });

      expect(foundEmptyText).toBe(true);
    });
  });

  // ── Conversation Items ─────────────────────────────────────────────────────

  describe("Conversation Item Classes", () => {
    it("active conversation has light mode background", () => {
      const { container } = render(<Sidebar {...defaultProps} />);

      const buttons = container.querySelectorAll("button");
      let activeButton: HTMLElement | null = null;

      buttons.forEach((btn) => {
        if (btn.title === "Test conversation") {
          activeButton = btn;
        }
      });

      if (activeButton) {
        expect(activeButton.className).toContain("bg-blue-50");
        expect(activeButton.className).toContain("text-gray-900");
      }
    });

    it("active conversation has dark mode background", () => {
      mockTheme = "dark";
      const { container } = render(<Sidebar {...defaultProps} />);

      const buttons = container.querySelectorAll("button");
      let activeButton: HTMLElement | null = null;

      buttons.forEach((btn) => {
        if (btn.title === "Test conversation") {
          activeButton = btn;
        }
      });

      if (activeButton) {
        expect(activeButton.className).toContain("bg-[#0071CE]/15");
        expect(activeButton.className).toContain("text-white");
      }
    });
  });

  // ── Group Headers ──────────────────────────────────────────────────────────

  describe("Group Header Classes", () => {
    it("group toggle button has correct classes", () => {
      mockTheme = "dark";
      const { container } = render(<Sidebar {...defaultProps} />);

      const groupHeaders = Array.from(container.querySelectorAll("button")).filter(
        (btn) => btn.textContent?.includes("Today") || btn.textContent?.includes("Yesterday")
      );

      groupHeaders.forEach((header) => {
        expect(header.className).toContain("hover:bg-[#21262d]");
        expect(header.className).toContain("text-gray-500");
      });

      expect(groupHeaders.length).toBeGreaterThan(0);
    });
  });

  // ── Theme Switching ────────────────────────────────────────────────────────

  describe("Theme Switching", () => {
    it("component renders different classes for light and dark themes", () => {
      // Light mode
      mockTheme = "light";
      const { container: lightContainer } = render(<Sidebar {...defaultProps} />);
      const lightAside = lightContainer.querySelector("aside");

      // Dark mode
      mockTheme = "dark";
      const { container: darkContainer } = render(<Sidebar {...defaultProps} />);
      const darkAside = darkContainer.querySelector("aside");

      expect(lightAside?.className).toContain("bg-white");
      expect(darkAside?.className).toContain("bg-[#161b22]");
      expect(lightAside?.className).not.toBe(darkAside?.className);
    });
  });

  // ── Footer Border ──────────────────────────────────────────────────────────

  describe("Border and Divider Classes", () => {
    it("sidebar footer has light mode border", () => {
      const { container } = render(<Sidebar {...defaultProps} />);
      const footerDiv = container.querySelector(".border-t");

      expect(footerDiv?.className).toContain("border-gray-100");
    });

    it("sidebar footer has dark mode border", () => {
      mockTheme = "dark";
      const { container } = render(<Sidebar {...defaultProps} />);
      const footerDiv = container.querySelector(".border-t");

      expect(footerDiv?.className).toContain("border-[#30363d]");
    });
  });
});
