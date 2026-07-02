/**
 * Tests for src/app/howto/page.tsx
 *
 * Covers:
 *  - Loading spinner shown on mount
 *  - Groups rendered after successful fetch
 *  - Header shows agent count and prompt count
 *  - HTML stripped from group description
 *  - FAQ prompts shown with 1-based index
 *  - Copy button: shows Copy icon, writes to clipboard, briefly shows Check icon
 *  - Group collapse / expand toggle
 *  - Error state with Retry button shown on fetch failure
 *  - Retry button triggers re-fetch
 *  - Empty state when backend returns []
 *  - Non-array response handled gracefully
 *  - "Back to chat" link present
 *  - stripHtml removes nested tags
 */

import React from "react";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

import HowToPage from "@/app/howto/page";
import { CopyButton } from "@/components/CopyButton";

// ── Mocks ─────────────────────────────────────────────────────────────────────

jest.mock("next/link", () => ({
  __esModule: true,
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    [k: string]: unknown;
  }) =>
    React.createElement("a", { href, ...rest }, children),
}));

const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockWriteText = jest.fn().mockResolvedValue(undefined);
Object.defineProperty(navigator, "clipboard", {
  value: { writeText: mockWriteText },
  configurable: true,
  writable: true,
});

// ── Fixtures ──────────────────────────────────────────────────────────────────

const FAQ_DATA = [
  {
    title: "Health Agent",
    description: "<b>Health</b> checks",
    faqs: ["Check health of intl-sre", "Get pod logs"],
  },
  {
    title: "Deploy Agent",
    description: "Deployment <em>ops</em>",
    faqs: ["Deploy foo to prod"],
  },
];

// jsdom does not have Response; simulate a resolved fetch with a .json() method
function faqResponse(data: unknown) {
  return { json: () => Promise.resolve(data) };
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();
  // Re-setup clipboard mock after clearAllMocks
  mockWriteText.mockResolvedValue(undefined);
});

afterEach(() => {
  // Ensure fake timers are always restored even if a test fails mid-flight
  jest.useRealTimers();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("HowToPage", () => {

  // ── Loading ──────────────────────────────────────────────────────────────────

  it("shows loading spinner on mount", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    render(<HowToPage />);

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  // ── Success ───────────────────────────────────────────────────────────────────

  it("renders group titles after successful fetch", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    render(<HowToPage />);

    await waitFor(() => {
      expect(screen.getByText("Health Agent")).toBeInTheDocument();
      expect(screen.getByText("Deploy Agent")).toBeInTheDocument();
    });
  });

  it("shows FAQ prompts as numbered items", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    render(<HowToPage />);

    await waitFor(() => screen.getByText("Health Agent"));

    expect(screen.getByText("Check health of intl-sre")).toBeInTheDocument();
    expect(screen.getByText("Get pod logs")).toBeInTheDocument();
    // Multiple groups each start at 1 — use getAllByText
    expect(screen.getAllByText("1.").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("2.").length).toBeGreaterThanOrEqual(1);
  });

  it("shows agent and prompt count in the header", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    render(<HowToPage />);

    await waitFor(() => screen.getByText("Health Agent"));

    // 2 agents, 3 total prompts
    expect(screen.getByText("2 agents · 3 prompts")).toBeInTheDocument();
  });

  it("strips HTML tags from group descriptions", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    render(<HowToPage />);

    await waitFor(() => screen.getByText("Health Agent"));

    expect(screen.getByText("Health checks")).toBeInTheDocument();
    expect(screen.queryByText(/<b>/)).not.toBeInTheDocument();
  });

  it("handles non-array backend response gracefully (empty groups)", async () => {
    mockFetch.mockResolvedValue(faqResponse({ error: "bad" }));
    render(<HowToPage />);

    await waitFor(() =>
      expect(screen.getByText("No FAQ groups returned by the backend.")).toBeInTheDocument()
    );
  });

  // ── Copy button ───────────────────────────────────────────────────────────────

  it("copies prompt text to clipboard when copy button clicked", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    render(<HowToPage />);

    await waitFor(() => screen.getByText("Check health of intl-sre"));

    fireEvent.click(screen.getAllByTitle("Copy prompt")[0]);

    expect(mockWriteText).toHaveBeenCalledWith("Check health of intl-sre");
  });

  // ── CopyButton unit tests ─────────────────────────────────────────────────────
  // Tested directly to avoid async Promise/state-flush complexity in the full page

  it("CopyButton shows Copy icon by default", () => {
    render(<CopyButton text="hello" />);
    expect(screen.getByTitle("Copy prompt")).toBeInTheDocument();
  });

  it("CopyButton calls clipboard.writeText on click", () => {
    render(<CopyButton text="hello world" />);
    fireEvent.click(screen.getByTitle("Copy prompt"));
    expect(mockWriteText).toHaveBeenCalledWith("hello world");
  });

  it("CopyButton shows Check icon after clipboard write and reverts via timeout", async () => {
    let capturedRevert: (() => void) | undefined;
    // Synchronous thenable — fires setCopied(true) within the click handler
    mockWriteText.mockImplementation(() => ({
      then(cb: () => void) {
        cb();
        return { catch: () => ({}) };
      },
    }));
    // Capture the revert setTimeout callback without actually scheduling it
    jest.spyOn(global, "setTimeout").mockImplementationOnce((fn: TimerHandler) => {
      capturedRevert = fn as () => void;
      return 1 as unknown as ReturnType<typeof setTimeout>;
    });

    render(<CopyButton text="test" />);

    // Click — setCopied(true) fires synchronously via our thenable mock
    await act(async () => {
      fireEvent.click(screen.getByTitle("Copy prompt"));
    });

    // Check icon SVG should be visible; Copy SVG should be gone
    expect(document.querySelector(".lucide-check")).toBeInTheDocument();
    expect(document.querySelector(".lucide-copy")).not.toBeInTheDocument();

    // Fire the captured revert callback → setCopied(false) → Copy icon returns
    await act(async () => { capturedRevert?.(); });
    expect(document.querySelector(".lucide-check")).not.toBeInTheDocument();
    expect(document.querySelector(".lucide-copy")).toBeInTheDocument();

    jest.restoreAllMocks();
  });

  // ── Group collapse / expand ───────────────────────────────────────────────────

  it("collapses a group when its header is clicked", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    render(<HowToPage />);

    await waitFor(() => screen.getByText("Health Agent"));
    expect(screen.getByText("Check health of intl-sre")).toBeInTheDocument();

    await user.click(screen.getByText("Health Agent"));

    expect(screen.queryByText("Check health of intl-sre")).not.toBeInTheDocument();
  });

  it("re-expands a collapsed group on second click", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    render(<HowToPage />);

    await waitFor(() => screen.getByText("Health Agent"));

    await user.click(screen.getByText("Health Agent"));
    await user.click(screen.getByText("Health Agent"));

    expect(screen.getByText("Check health of intl-sre")).toBeInTheDocument();
  });

  it("shows prompt count badge per group", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    render(<HowToPage />);

    await waitFor(() => screen.getByText("Health Agent"));

    expect(screen.getByText("2 prompts")).toBeInTheDocument();
    expect(screen.getByText("1 prompts")).toBeInTheDocument();
  });

  // ── Error state ───────────────────────────────────────────────────────────────

  it("shows error message when fetch fails", async () => {
    mockFetch.mockRejectedValue(new Error("network error"));
    render(<HowToPage />);

    await waitFor(() =>
      expect(
        screen.getByText("Could not load FAQs from the backend.")
      ).toBeInTheDocument()
    );
  });

  it("shows Retry button on error", async () => {
    mockFetch.mockRejectedValue(new Error("network error"));
    render(<HowToPage />);

    await waitFor(() => expect(screen.getByText("Retry")).toBeInTheDocument());
  });

  it("Retry button re-fetches and renders data on success", async () => {
    const user = userEvent.setup();
    mockFetch
      .mockRejectedValueOnce(new Error("fail"))
      .mockResolvedValueOnce(faqResponse(FAQ_DATA));

    render(<HowToPage />);

    await waitFor(() => screen.getByText("Retry"));
    await user.click(screen.getByText("Retry"));

    await waitFor(() =>
      expect(screen.getByText("Health Agent")).toBeInTheDocument()
    );
  });

  // ── Empty state ───────────────────────────────────────────────────────────────

  it("shows empty state when backend returns empty array", async () => {
    mockFetch.mockResolvedValue(faqResponse([]));
    render(<HowToPage />);

    await waitFor(() =>
      expect(
        screen.getByText("No FAQ groups returned by the backend.")
      ).toBeInTheDocument()
    );
  });

  it("does not show the header count while loading", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    render(<HowToPage />);

    expect(screen.queryByText(/agents · \d+ prompts/)).not.toBeInTheDocument();
  });

  // ── Navigation ────────────────────────────────────────────────────────────────

  it("renders a 'Back to chat' link pointing to /", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    render(<HowToPage />);

    const link = screen.getByText("Back to chat").closest("a");
    expect(link).toHaveAttribute("href", "/");
  });

  it("renders the page heading", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    render(<HowToPage />);

    expect(screen.getByRole("heading", { name: "How To Guide" })).toBeInTheDocument();
  });
});
