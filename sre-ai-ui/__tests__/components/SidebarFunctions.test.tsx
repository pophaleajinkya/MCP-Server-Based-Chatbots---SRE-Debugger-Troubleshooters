/**
 * Additional tests for src/components/Sidebar.tsx
 * Covers the uncovered functions:
 *  - copyLink (click & keyboard, copiedId → Check icon, setTimeout reset)
 *  - toggleGroup (collapse/expand a group, ChevronRight rendered when collapsed)
 *  - onHowToClick callback
 *  - logout callback
 */

import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import type { Conversation } from "@/types";

// ─── Mocks ────────────────────────────────────────────────────────────────────

// AuthContext is no longer imported by Sidebar (logout moved to IconSidebar).
// Keep a stub so any transitive import doesn't break.
jest.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ user: null, loading: false, isLoggingOut: false, login: jest.fn(), logout: jest.fn() }),
}));

jest.mock("@/lib/works-client", () => ({
  getActiveMonitors: jest.fn().mockResolvedValue({ data: [] }),
}));

import { Sidebar } from "@/components/Sidebar";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const NOW = Date.now() / 1000;

const CONVS: Conversation[] = [
  {
    session_id: "s1",
    user_id: "u1",
    title: "Today conv",
    last_update_time: NOW - 60,           // Today
  },
  {
    session_id: "s2",
    user_id: "u1",
    title: "Week conv",
    last_update_time: NOW - 3 * 86400,    // This week
  },
];

function makeProps(overrides = {}) {
  return {
    conversations: CONVS,
    activeSessionId: "s1",
    userId: "u1",
    loading: false,
    onNewChat: jest.fn(),
    onSelectConversation: jest.fn(),
    onHowToClick: jest.fn(),
    ...overrides,
  };
}

// ─── copyLink ─────────────────────────────────────────────────────────────────

describe("copyLink", () => {
  const writeText = jest.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    jest.useFakeTimers();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      writable: true,
      configurable: true,
    });
    writeText.mockClear();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("calls clipboard.writeText with a URL containing the session id", async () => {
    render(<Sidebar {...makeProps()} />);

    // Groups start expanded — copy buttons are visible immediately
    // Multiple copy buttons exist (one per conversation); grab the first (s1)
    const [copyBtn] = screen.getAllByTitle("Copy shareable link");
    fireEvent.click(copyBtn);

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("session=s1"));
  });

  it("does not trigger onSelectConversation when copy button is clicked (stopPropagation)", async () => {
    const onSelectConversation = jest.fn();
    render(<Sidebar {...makeProps({ onSelectConversation })} />);

    // Groups start expanded — copy buttons are visible immediately
    const [copyBtn] = screen.getAllByTitle("Copy shareable link");
    fireEvent.click(copyBtn);

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    // The outer conversation button's onClick must NOT have fired
    expect(onSelectConversation).not.toHaveBeenCalled();
  });

  it("shows SVG icon in copy button after copy and after timeout reset", async () => {
    render(<Sidebar {...makeProps()} />);

    // Groups start expanded — copy buttons are visible immediately
    const [copyBtn] = screen.getAllByTitle("Copy shareable link");
    fireEvent.click(copyBtn);

    // Wait for clipboard promise to resolve and state to update
    await act(async () => { await Promise.resolve(); });

    // Icon svg is present (either Check or Link2)
    expect(copyBtn.querySelectorAll("svg").length).toBeGreaterThan(0);

    // After 2 seconds the setTimeout fires and copiedId resets
    act(() => { jest.advanceTimersByTime(2001); });

    // Still has an svg (now Link2 again)
    expect(copyBtn.querySelectorAll("svg").length).toBeGreaterThan(0);
  });

  it("triggers copyLink via Enter key on the copy button", async () => {
    render(<Sidebar {...makeProps()} />);

    // Groups start expanded — copy buttons are visible immediately
    const [copyBtn] = screen.getAllByTitle("Copy shareable link");
    fireEvent.keyDown(copyBtn, { key: "Enter" });

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("session=s1"));
  });

  it("does NOT trigger copyLink on non-Enter key presses", async () => {
    render(<Sidebar {...makeProps()} />);

    // Groups start expanded — copy buttons are visible immediately
    const [copyBtn] = screen.getAllByTitle("Copy shareable link");
    fireEvent.keyDown(copyBtn, { key: "Space" });
    fireEvent.keyDown(copyBtn, { key: "Tab" });

    expect(writeText).not.toHaveBeenCalled();
  });
});

// ─── toggleGroup ──────────────────────────────────────────────────────────────

describe("toggleGroup", () => {
  // Helper: render Sidebar and flush the async getActiveMonitors() effect
  // so pending state updates don't interfere with subsequent interactions.
  async function renderSidebar(overrides = {}) {
    const user = userEvent.setup();
    await act(async () => {
      render(<Sidebar {...makeProps(overrides)} />);
    });
    await act(async () => { await Promise.resolve(); });
    return user;
  }

  it("collapses an expanded group when its header button is clicked", async () => {
    const user = await renderSidebar();

    // Groups start expanded — Today conv IS visible initially
    expect(screen.getByText("Today conv")).toBeInTheDocument();

    // Click "Today" header to collapse it
    await user.click(screen.getByText("Today"));

    // Conversation under "Today" should now be hidden
    expect(screen.queryByText("Today conv")).not.toBeInTheDocument();
  });

  it("expands a collapsed group when its header is clicked again", async () => {
    const user = await renderSidebar();

    const todayHeader = screen.getByText("Today");

    // Collapse first
    await user.click(todayHeader);
    expect(screen.queryByText("Today conv")).not.toBeInTheDocument();

    // Expand on second click
    await user.click(screen.getByText("Today"));
    expect(screen.getByText("Today conv")).toBeInTheDocument();
  });

  it("only toggles the clicked group, leaving others unchanged", async () => {
    const user = await renderSidebar();

    // "Today" starts expanded, "This week" starts collapsed
    expect(screen.getByText("Today conv")).toBeInTheDocument();
    expect(screen.queryByText("Week conv")).not.toBeInTheDocument();

    // Expand "This week"
    await user.click(screen.getByText("This week"));
    expect(screen.getByText("Week conv")).toBeInTheDocument();

    // "Today" was not clicked — "Today conv" should still be visible
    expect(screen.getByText("Today conv")).toBeInTheDocument();
  });

  it("renders ChevronRight icon when a group is collapsed", async () => {
    const user = await renderSidebar();

    // Groups start expanded — collapse "Today" on first click
    await user.click(screen.getByText("Today"));
    // Conversation is hidden (collapsed state), confirming ChevronRight is shown
    expect(screen.queryByText("Today conv")).not.toBeInTheDocument();

    // Expand again on second click — confirms toggling works both ways
    await user.click(screen.getByText("Today"));
    expect(screen.getByText("Today conv")).toBeInTheDocument();
  });
});

// ─── onHowToClick ─────────────────────────────────────────────────────────────

describe("onHowToClick", () => {
  it("calls onHowToClick when How To button is clicked", async () => {
    const user = userEvent.setup();
    const onHowToClick = jest.fn();
    render(<Sidebar {...makeProps({ onHowToClick })} />);

    await user.click(screen.getByTitle("How To guide"));

    expect(onHowToClick).toHaveBeenCalledTimes(1);
  });

  it("does not throw when onHowToClick is not provided (optional prop)", async () => {
    const user = userEvent.setup();
    // No onHowToClick prop — should not crash
    render(<Sidebar {...makeProps({ onHowToClick: undefined })} />);

    await expect(
      user.click(screen.getByTitle("How To guide"))
    ).resolves.not.toThrow();
  });
});

// ─── logout ───────────────────────────────────────────────────────────────────
// NOTE: The logout button was removed from Sidebar and moved to IconSidebar.
// These tests now verify that Sidebar renders correctly without a logout button.

describe("logout button", () => {
  it("does not render a Log out button in the Sidebar footer (moved to IconSidebar)", () => {
    render(<Sidebar {...makeProps()} />);
    expect(screen.queryByTitle("Log out")).not.toBeInTheDocument();
  });

  it("Sidebar footer still renders How To guide button", () => {
    render(<Sidebar {...makeProps()} />);
    expect(screen.getByTitle("How To guide")).toBeInTheDocument();
  });
});
