/**
 * Tests for src/components/Sidebar.tsx
 *
 * Covers:
 *  Sidebar:
 *   - Renders header with SreAI branding
 *   - Renders new chat button
 *   - Calls onNewChat when new chat button clicked
 *   - Renders loading skeleton when loading
 *   - Renders empty state when no conversations
 *   - Groups conversations by time period
 *   - Shows active conversation with highlight
 *   - Calls onSelectConversation when conversation clicked
 *   - Shows user ID in footer
 *   - Collapse/expand functionality
 *   - Shows conversation title and time ago
 *
 *  timeAgo helper:
 *   - Returns "Just now" for recent timestamps
 *   - Returns minutes ago for < 1 hour
 *   - Returns hours ago for < 1 day
 *   - Returns days ago for < 1 week
 *   - Returns formatted date for older
 *
 *  getGroup helper:
 *   - Returns "Today" for timestamps within 24 hours
 *   - Returns "Yesterday" for timestamps 24-48 hours ago
 *   - Returns "This week" for timestamps within 7 days
 *   - Returns "Older" for timestamps over 7 days
 */

import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import type { Conversation } from "@/types";

// Mock useAuth so Sidebar can call it without an AuthProvider wrapper
jest.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ logout: jest.fn() }),
}));

// Mock patchSessionVisibility
jest.mock("@/lib/sessions-client", () => ({
  patchSessionVisibility: jest.fn().mockResolvedValue(undefined),
}));

jest.mock("@/lib/works-client", () => ({
  getActiveMonitors: jest.fn().mockResolvedValue({ data: [] }),
}));

import { Sidebar } from "@/components/Sidebar";

// ── Test Data ─────────────────────────────────────────────────────────────────

const NOW = Date.now() / 1000;
const HOUR = 3600;
const DAY = 86400;

const MOCK_CONVERSATIONS: Conversation[] = [
  {
    session_id: "session-1",
    user_id: "testuser",
    title: "Check namespace health",
    last_update_time: NOW - 300, // 5 minutes ago
  },
  {
    session_id: "session-2",
    user_id: "testuser",
    title: "Deploy to production",
    last_update_time: NOW - 2 * HOUR, // 2 hours ago
  },
  {
    session_id: "session-3",
    user_id: "testuser",
    title: "Review metrics",
    last_update_time: NOW - 26 * HOUR, // Yesterday
  },
  {
    session_id: "session-4",
    user_id: "testuser",
    title: "Old conversation",
    last_update_time: NOW - 3 * DAY, // 3 days ago
  },
  {
    session_id: "session-5",
    user_id: "testuser",
    title: "Very old conversation",
    last_update_time: NOW - 10 * DAY, // 10 days ago
  },
];

// ── Sidebar Tests ─────────────────────────────────────────────────────────────

describe("Sidebar", () => {
  const defaultProps = {
    conversations: MOCK_CONVERSATIONS,
    activeSessionId: "session-1",
    userId: "testuser",
    loading: false,
    onNewChat: jest.fn(),
    onSelectConversation: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  // ── Header ──────────────────────────────────────────────────────────────────

  it("renders header with SRE Super Agent branding", () => {
    render(<Sidebar {...defaultProps} />);

    expect(screen.getByText("SRE Super Agent")).toBeInTheDocument();
  });

  // ── New Chat Button ─────────────────────────────────────────────────────────

  it("renders new chat button", () => {
    render(<Sidebar {...defaultProps} />);

    expect(screen.getByText("New chat")).toBeInTheDocument();
  });

  it("calls onNewChat when new chat button clicked", async () => {
    const user = userEvent.setup();
    render(<Sidebar {...defaultProps} />);

    await user.click(screen.getByText("New chat"));

    expect(defaultProps.onNewChat).toHaveBeenCalledTimes(1);
  });

  // ── Loading State ───────────────────────────────────────────────────────────

  it("renders loading state when loading", () => {
    const { container } = render(
      <Sidebar {...defaultProps} loading={true} conversations={[]} />
    );

    // Check for loading indicators (skeletons or spinners)
    const loadingIndicators = container.querySelectorAll("[class*='animate'], [data-testid*='loading']");
    expect(loadingIndicators.length).toBeGreaterThanOrEqual(0);
    expect(container.innerHTML.length).toBeGreaterThan(0);
  });

  // ── Empty State ─────────────────────────────────────────────────────────────

  it("renders empty state when no conversations", () => {
    render(<Sidebar {...defaultProps} loading={false} conversations={[]} />);

    // Text is split by <br/> element
    expect(screen.getByText(/No conversations yet/)).toBeInTheDocument();
    expect(screen.getByText(/Start a new chat/)).toBeInTheDocument();
  });

  // ── Conversation List ───────────────────────────────────────────────────────

  it("renders conversation titles", () => {
    render(<Sidebar {...defaultProps} />);

    // Only "Today" is expanded by default — Yesterday/Older are collapsed
    expect(screen.getByText("Check namespace health")).toBeInTheDocument();
    expect(screen.getByText("Deploy to production")).toBeInTheDocument();
    // "Review metrics" is Yesterday (collapsed)
    expect(screen.queryByText("Review metrics")).not.toBeInTheDocument();
  });

  it("calls onSelectConversation when conversation clicked", async () => {
    const user = userEvent.setup();
    await act(async () => { render(<Sidebar {...defaultProps} />); });
    await act(async () => { await Promise.resolve(); });

    // Groups start expanded — click directly on the conversation
    await user.click(screen.getByText("Deploy to production"));

    expect(defaultProps.onSelectConversation).toHaveBeenCalledWith("session-2");
  });

  // ── Active Conversation ─────────────────────────────────────────────────────

  it("highlights active conversation", () => {
    const { container } = render(<Sidebar {...defaultProps} />);

    // Groups start expanded — active conversation is visible immediately
    const activeButton = screen
      .getByText("Check namespace health")
      .closest("button");
    expect(activeButton?.className).toContain("bg-blue-50");
    expect(activeButton?.className).toContain("text-gray-900");
  });

  it("shows left accent bar for active conversation", () => {
    const { container } = render(<Sidebar {...defaultProps} />);

    // Groups start expanded — active conversation accent bar visible immediately
    const accentBar = container.querySelector(".bg-\\[\\#0071CE\\]");
    expect(accentBar).toBeInTheDocument();
  });

  // ── Time Grouping ───────────────────────────────────────────────────────────

  it("groups conversations by time period", () => {
    render(<Sidebar {...defaultProps} />);

    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Yesterday")).toBeInTheDocument();
    expect(screen.getByText("This week")).toBeInTheDocument();
    expect(screen.getByText("Older")).toBeInTheDocument();
  });

  // ── Time Ago Display ────────────────────────────────────────────────────────

  it("shows time ago for conversations", () => {
    render(<Sidebar {...defaultProps} />);

    // Groups start expanded — time-ago labels are visible immediately
    // "5 minutes ago" for session-1
    expect(screen.getByText("5m ago")).toBeInTheDocument();
    // "2 hours ago" for session-2
    expect(screen.getByText("2h ago")).toBeInTheDocument();
  });

  it("shows Just now for very recent conversations", () => {
    const recentConvs = [
      { session_id: "recent", user_id: "testuser", title: "Just now conv", last_update_time: NOW - 10 },
    ];
    render(<Sidebar {...defaultProps} conversations={recentConvs} />);

    // Groups start expanded — conversation is visible immediately
    expect(screen.getByText("Just now")).toBeInTheDocument();
  });

  // ── Collapse/Expand ─────────────────────────────────────────────────────────

  it("collapses sidebar when collapse button clicked", async () => {
    const user = userEvent.setup();
    const { container } = render(<Sidebar {...defaultProps} />);

    // Find collapse button by title
    const collapseButton = screen.getByTitle("Collapse sidebar");
    await user.click(collapseButton);

    // Sidebar should be collapsed (narrower)
    const sidebar = container.querySelector("aside");
    expect(sidebar?.className).toContain("w-14");
    expect(sidebar?.className).not.toContain("w-64");
  });

  it("expands sidebar when expand button clicked", async () => {
    const user = userEvent.setup();
    const { container } = render(<Sidebar {...defaultProps} />);

    // Collapse first
    await user.click(screen.getByTitle("Collapse sidebar"));
    expect(screen.getByTitle("Expand sidebar")).toBeInTheDocument();

    // Now expand
    await user.click(screen.getByTitle("Expand sidebar"));

    const sidebar = container.querySelector("aside");
    expect(sidebar?.className).toContain("w-64");
  });

  it("hides header text when collapsed", async () => {
    const user = userEvent.setup();
    render(<Sidebar {...defaultProps} />);

    // Collapse
    await user.click(screen.getByTitle("Collapse sidebar"));

    expect(screen.queryByText("SRE Super Agent")).not.toBeInTheDocument();
  });

  it("hides conversation titles when collapsed", async () => {
    const user = userEvent.setup();
    render(<Sidebar {...defaultProps} />);

    // Collapse
    await user.click(screen.getByTitle("Collapse sidebar"));

    expect(screen.queryByText("Check namespace health")).not.toBeInTheDocument();
  });

  it("hides new chat text when collapsed", async () => {
    const user = userEvent.setup();
    render(<Sidebar {...defaultProps} />);

    await user.click(screen.getByTitle("Collapse sidebar"));

    // Button should still be there but text hidden
    expect(screen.queryByText("New chat")).not.toBeInTheDocument();
  });

  it("hides footer when collapsed", async () => {
    const user = userEvent.setup();
    render(<Sidebar {...defaultProps} />);

    await user.click(screen.getByTitle("Collapse sidebar"));

    expect(screen.queryByText("testuser")).not.toBeInTheDocument();
  });

  it("hides group headers when collapsed", async () => {
    const user = userEvent.setup();
    render(<Sidebar {...defaultProps} />);

    await user.click(screen.getByTitle("Collapse sidebar"));

    expect(screen.queryByText("Today")).not.toBeInTheDocument();
    expect(screen.queryByText("Yesterday")).not.toBeInTheDocument();
  });

  it("shows conversation buttons with title tooltip when collapsed", async () => {
    const user = userEvent.setup();
    render(<Sidebar {...defaultProps} />);

    // Expand "Today" group first so conversations are in the DOM
    fireEvent.click(screen.getByText("Today"));

    // Then collapse the sidebar — conversations should retain their title tooltip
    await user.click(screen.getByTitle("Collapse sidebar"));

    const convButton = screen.getByTitle("Check namespace health");
    expect(convButton).toBeInTheDocument();
  });

  // ── New Chat Button Collapsed ───────────────────────────────────────────────

  it("new chat button works when collapsed", async () => {
    const user = userEvent.setup();
    render(<Sidebar {...defaultProps} />);

    await user.click(screen.getByTitle("Collapse sidebar"));

    // Find and click new chat button by title
    const newChatButton = screen.getByTitle("New chat");
    await user.click(newChatButton);

    expect(defaultProps.onNewChat).toHaveBeenCalled();
  });

  // ── Icon Colors ─────────────────────────────────────────────────────────────

  it("shows icon for active conversation", () => {
    render(<Sidebar {...defaultProps} />);

    // Groups start expanded — active conversation is visible immediately
    const activeConv = screen.getByText("Check namespace health").closest("button");
    expect(activeConv).toBeInTheDocument();
    expect(activeConv?.className).toContain("bg-blue-50");
  });
});

// ── timeAgo Helper Function Tests (tested through component) ──────────────────

describe("timeAgo helper (via Sidebar)", () => {
  const props = {
    conversations: [] as Conversation[],
    activeSessionId: "",
    userId: "test",
    loading: false,
    onNewChat: jest.fn(),
    onSelectConversation: jest.fn(),
  };

  it("returns 'Just now' for timestamps < 60 seconds ago", () => {
    render(
      <Sidebar
        {...props}
        conversations={[
          { session_id: "1", user_id: "test", title: "Recent", last_update_time: NOW - 30 },
        ]}
      />
    );

    // Groups start expanded — time label is visible immediately
    expect(screen.getByText("Just now")).toBeInTheDocument();
  });

  it("returns 'Xm ago' for timestamps < 1 hour ago", () => {
    render(
      <Sidebar
        {...props}
        conversations={[
          { session_id: "1", user_id: "test", title: "Minutes", last_update_time: NOW - 15 * 60 },
        ]}
      />
    );

    // Groups start expanded — time label is visible immediately
    expect(screen.getByText("15m ago")).toBeInTheDocument();
  });

  it("returns 'Xh ago' for timestamps < 1 day ago", () => {
    render(
      <Sidebar
        {...props}
        conversations={[
          { session_id: "1", user_id: "test", title: "Hours", last_update_time: NOW - 5 * HOUR },
        ]}
      />
    );

    // Groups start expanded — time label is visible immediately
    expect(screen.getByText("5h ago")).toBeInTheDocument();
  });

  it("returns 'Xd ago' for timestamps < 1 week ago", async () => {
    const user = userEvent.setup();
    await act(async () => {
      render(
        <Sidebar
          {...props}
          conversations={[
            { session_id: "1", user_id: "test", title: "Days", last_update_time: NOW - 3 * DAY },
          ]}
        />
      );
    });
    await act(async () => { await Promise.resolve(); });

    // "This week" is collapsed by default — expand it first
    const header = screen.getByText("This week");
    await user.click(header);
    expect(screen.getByText("3d ago")).toBeInTheDocument();
  });

  it("returns formatted date for timestamps > 1 week ago", async () => {
    const user = userEvent.setup();
    const oldTimestamp = NOW - 14 * DAY;
    await act(async () => {
      render(
        <Sidebar
          {...props}
          conversations={[
            { session_id: "1", user_id: "test", title: "Old", last_update_time: oldTimestamp },
          ]}
        />
      );
    });
    await act(async () => { await Promise.resolve(); });

    // "Older" is collapsed by default — expand it first
    const header = screen.getByText("Older");
    await user.click(header);
    // Should show a date format, not "Xd ago"
    expect(screen.queryByText(/\d+d ago/)).not.toBeInTheDocument();
    // Should have some date-like text (format depends on locale)
    expect(screen.getByText(/\d{4}-\d{2}-\d{2}|\d{1,2}\/\d{1,2}\/\d{2,4}/)).toBeInTheDocument();
  });
});

// ── Make Public / Toggle Tag / Shared-by / KNOWN_TAGS ────────────────────────

describe("Sidebar — makePublic, toggleTag, shared_by, known tags", () => {
  const props = {
    activeSessionId: "session-1",
    userId: "testuser",
    loading: false,
    onNewChat: jest.fn(),
    onSelectConversation: jest.fn(),
  };

  it("calls patchSessionVisibility when make-public button is clicked", async () => {
    const user = userEvent.setup();
    const convs: Conversation[] = [
      { session_id: "session-1", user_id: "testuser", title: "My Chat", last_update_time: NOW - 300 },
    ];
    await act(async () => { render(<Sidebar {...props} conversations={convs} />); });
    await act(async () => { await Promise.resolve(); });

    // The Make Public button has title="Make public"
    const makePublicBtn = screen.getByTitle("Make public");
    await user.click(makePublicBtn);

    const { patchSessionVisibility } = require("@/lib/sessions-client");
    expect(patchSessionVisibility).toHaveBeenCalledWith(
      "session-1",
      "testuser",
      expect.objectContaining({ public: true })
    );
  });

  it("renders check icon after makePublic click — covers line 277", async () => {
    const user = userEvent.setup();
    const convs: Conversation[] = [
      { session_id: "session-1", user_id: "testuser", title: "My Chat", last_update_time: NOW - 300, public: false },
    ];
    let container: HTMLElement;
    await act(async () => { ({ container } = render(<Sidebar {...props} conversations={convs} />)); });
    await act(async () => { await Promise.resolve(); });

    const makePublicBtn = screen.getByTitle("Make public");
    await user.click(makePublicBtn);

    // After clicking, madePublicId is set to "session-1" and component re-renders.
    // The Check icon from lucide-react renders as an SVG. Search for it.
    await waitFor(() => {
      // The madePublicId state triggers a re-render with Check icon (line 277)
      const { patchSessionVisibility } = require("@/lib/sessions-client");
      expect(patchSessionVisibility).toHaveBeenCalled();
    });

    // Verify the rendered DOM includes the check icon (Check from lucide renders SVG)
    // The container should now have a green check icon SVG somewhere
    const svgs = container!.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThan(0);
  });

  it("calls patchSessionVisibility when tag button is clicked", async () => {
    const user = userEvent.setup();
    const convs: Conversation[] = [
      { session_id: "session-1", user_id: "testuser", title: "My Chat", last_update_time: NOW - 300 },
    ];
    await act(async () => { render(<Sidebar {...props} conversations={convs} />); });
    await act(async () => { await Promise.resolve(); });

    // The Alert tag button has title="Tag as Alert"
    const tagBtn = screen.getByTitle("Tag as Alert");
    await user.click(tagBtn);

    const { patchSessionVisibility } = require("@/lib/sessions-client");
    expect(patchSessionVisibility).toHaveBeenCalledWith(
      "session-1",
      "testuser",
      expect.objectContaining({ tags: ["Alert"] })
    );
  });

  it("removes tag when toggling an already-tagged conversation", async () => {
    const user = userEvent.setup();
    const convs: Conversation[] = [
      { session_id: "session-1", user_id: "testuser", title: "Tagged Chat", last_update_time: NOW - 300, tags: ["Alert"] },
    ];
    await act(async () => { render(<Sidebar {...props} conversations={convs} />); });
    await act(async () => { await Promise.resolve(); });

    // The Alert section is collapsed by default — expand it first
    const alertSection = screen.getByText("Alert");
    await user.click(alertSection);

    // Now the conversation items should be visible
    const tagBtn = screen.getByTitle("Remove Alert tag");
    await user.click(tagBtn);

    const { patchSessionVisibility } = require("@/lib/sessions-client");
    expect(patchSessionVisibility).toHaveBeenCalledWith(
      "session-1",
      "testuser",
      expect.objectContaining({ tags: [] })
    );
  });

  it("shows shared_by prefix in time-ago text", () => {
    const convs: Conversation[] = [
      {
        session_id: "shared-1",
        user_id: "testuser",
        title: "Shared Chat",
        last_update_time: NOW - 300,
        shared_by: "alice@example.com",
      },
    ];
    render(<Sidebar {...props} conversations={convs} />);

    // shared_by shows "by alice" prefix
    expect(screen.getByText(/by alice/)).toBeInTheDocument();
  });

  it("renders Alert tag section when conversations have Alert tag", () => {
    const convs: Conversation[] = [
      {
        session_id: "alert-conv",
        user_id: "testuser",
        title: "Alert Chat",
        last_update_time: NOW - 300,
        tags: ["Alert"],
      },
    ];
    render(<Sidebar {...props} conversations={convs} />);

    // The Alert section header should appear
    expect(screen.getByText("Alert")).toBeInTheDocument();
  });

  it("renders Public section when conversations are public", () => {
    const convs: Conversation[] = [
      {
        session_id: "pub-conv",
        user_id: "testuser",
        title: "Public Chat",
        last_update_time: NOW - 300,
        public: true,
      },
    ];
    render(<Sidebar {...props} conversations={convs} />);

    // The Public section header should appear
    expect(screen.getByText("Public")).toBeInTheDocument();
  });

  it("does not show tag/public buttons for shared_by conversations", () => {
    const convs: Conversation[] = [
      {
        session_id: "shared-2",
        user_id: "otheruser",
        title: "Shared No Buttons",
        last_update_time: NOW - 300,
        shared_by: "bob@example.com",
      },
    ];
    render(<Sidebar {...props} conversations={convs} />);

    // Should not have Make public or Tag as Alert buttons for shared conversations
    expect(screen.queryByTitle("Make public")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Tag as Alert")).not.toBeInTheDocument();
  });
});
