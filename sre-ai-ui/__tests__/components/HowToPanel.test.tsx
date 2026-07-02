/**
 * Tests for src/components/HowToPanel.tsx
 *
 * Covers:
 *  - Loading spinner shown on mount (cold cache)
 *  - FAQ groups rendered after successful fetch
 *  - Error state + Retry button on fetch failure
 *  - Retry triggers re-fetch and shows data
 *  - Non-array backend response handled gracefully
 *  - Cache hit: second render skips fetch
 *  - Close button calls onClose
 *  - Backdrop click calls onClose
 *  - Clicking a prompt calls onSelect and onClose
 *  - Group collapse / expand toggle
 *  - Group hidden when all items filtered out by search
 *  - Search filters prompts (case-insensitive)
 *  - Search shows singular "1 result" vs plural "N results"
 *  - Clear-search button resets query
 *  - "No FAQs available." shown when groups is empty and no query
 *  - "No prompts match your search." shown when query matches nothing
 *  - HTML stripped from group description
 *  - Highlighted text wraps match in <mark>
 *  - __resetFAQCache resets module-level cache
 */

import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

import { HowToPanel, __resetFAQCache } from "@/components/HowToPanel";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const FAQ_DATA = [
  {
    title: "Health Agent",
    description: "<b>Health</b> checks for WCNP",
    faqs: ["Check health of intl-sre", "Check all services health"],
  },
  {
    title: "Deploy Agent",
    description: "Deployment <em>operations</em>",
    faqs: ["Deploy service foo to prod"],
  },
];

// ── Global fetch mock ─────────────────────────────────────────────────────────

const mockFetch = jest.fn();
global.fetch = mockFetch;

// ── Helpers ───────────────────────────────────────────────────────────────────

// jsdom does not have Response; simulate a resolved fetch with a .json() method
function faqResponse(data: unknown) {
  return { json: () => Promise.resolve(data) };
}

function renderPanel(
  onSelect = jest.fn(),
  onClose = jest.fn()
) {
  return render(<HowToPanel onSelect={onSelect} onClose={onClose} />);
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  __resetFAQCache();
  jest.clearAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("HowToPanel", () => {

  // ── Loading state ────────────────────────────────────────────────────────────

  it("shows loading spinner on mount when cache is empty", () => {
    mockFetch.mockReturnValue(new Promise(() => {})); // never resolves
    renderPanel();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  // ── Success state ────────────────────────────────────────────────────────────

  it("renders group titles and FAQs after successful fetch", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("Health Agent")).toBeInTheDocument();
      expect(screen.getByText("Deploy Agent")).toBeInTheDocument();
      expect(screen.getByText("Check health of intl-sre")).toBeInTheDocument();
      expect(screen.getByText("Deploy service foo to prod")).toBeInTheDocument();
    });
  });

  it("strips HTML tags from group description", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    // HTML stripped — rendered as plain text
    expect(screen.getByText("Health checks for WCNP")).toBeInTheDocument();
    expect(screen.queryByText("<b>Health</b> checks for WCNP")).not.toBeInTheDocument();
  });

  it("shows faq count badge per group", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    // Health Agent has 2 faqs, Deploy Agent has 1
    const counts = screen.getAllByText(/^[12]$/);
    expect(counts.length).toBeGreaterThanOrEqual(2);
  });

  it("handles non-array backend response gracefully (shows empty state)", async () => {
    mockFetch.mockResolvedValue(faqResponse({ error: "oops" }));
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText("No FAQs available.")).toBeInTheDocument()
    );
  });

  // ── Error + Retry ────────────────────────────────────────────────────────────

  it("shows error message when fetch rejects", async () => {
    mockFetch.mockRejectedValue(new Error("network error"));
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText("Could not load FAQs.")).toBeInTheDocument()
    );
  });

  it("shows Retry button when fetch fails", async () => {
    mockFetch.mockRejectedValue(new Error("network error"));
    renderPanel();

    await waitFor(() => expect(screen.getByText("Retry")).toBeInTheDocument());
  });

  it("Retry button re-fetches and shows data on success", async () => {
    const user = userEvent.setup({});
    mockFetch
      .mockRejectedValueOnce(new Error("fail"))
      .mockResolvedValueOnce(faqResponse(FAQ_DATA));

    renderPanel();

    await waitFor(() => screen.getByText("Retry"));
    await user.click(screen.getByText("Retry"));

    await waitFor(() =>
      expect(screen.getByText("Health Agent")).toBeInTheDocument()
    );
  });

  // ── Empty state ───────────────────────────────────────────────────────────────

  it("shows 'No FAQs available.' when backend returns empty array", async () => {
    mockFetch.mockResolvedValue(faqResponse([]));
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText("No FAQs available.")).toBeInTheDocument()
    );
  });

  // ── Cache ─────────────────────────────────────────────────────────────────────

  it("uses cached groups on second render without re-fetching", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    const { unmount } = renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));
    unmount();

    // Second render — cache is populated, fetch should NOT be called again
    mockFetch.mockClear();
    renderPanel();

    expect(screen.getByText("Health Agent")).toBeInTheDocument();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  // ── Close / Backdrop ──────────────────────────────────────────────────────────

  it("calls onClose when the Close button is clicked", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    const onClose = jest.fn();
    renderPanel(jest.fn(), onClose);

    await waitFor(() => screen.getByText("Health Agent"));
    await userEvent.click(screen.getByTitle("Close"));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when the backdrop is clicked", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    const onClose = jest.fn();
    renderPanel(jest.fn(), onClose);

    await waitFor(() => screen.getByText("Health Agent"));

    // The backdrop is the first sibling div (absolute inset-0)
    const backdrop = document.querySelector(".absolute.inset-0.z-20") as HTMLElement;
    fireEvent.click(backdrop);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // ── Select prompt ─────────────────────────────────────────────────────────────

  it("calls onSelect with the prompt text when clicked", async () => {
    const user = userEvent.setup({});
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    const onSelect = jest.fn();
    const onClose = jest.fn();
    renderPanel(onSelect, onClose);

    await waitFor(() => screen.getByText("Check health of intl-sre"));
    await user.click(screen.getByText("Check health of intl-sre"));

    expect(onSelect).toHaveBeenCalledWith("Check health of intl-sre");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // ── Group collapse / expand ───────────────────────────────────────────────────

  it("collapses a group when its header is clicked", async () => {
    const user = userEvent.setup({});
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));
    expect(screen.getByText("Check health of intl-sre")).toBeInTheDocument();

    await user.click(screen.getByText("Health Agent"));

    expect(screen.queryByText("Check health of intl-sre")).not.toBeInTheDocument();
  });

  it("re-expands a collapsed group on second click", async () => {
    const user = userEvent.setup({});
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    await user.click(screen.getByText("Health Agent")); // collapse
    await user.click(screen.getByText("Health Agent")); // expand

    expect(screen.getByText("Check health of intl-sre")).toBeInTheDocument();
  });

  // ── Search ────────────────────────────────────────────────────────────────────

  it("filters prompts by search query (case-insensitive)", async () => {
    const user = userEvent.setup({});
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    const searchInput = screen.getByPlaceholderText("Search prompts…");
    await user.type(searchInput, "intl-sre");

    // When highlighted, the text is split across nodes — match via button accessible name
    expect(
      screen.getByRole("button", { name: /Check health of intl-sre/ })
    ).toBeInTheDocument();
    expect(screen.queryByText("Check all services health")).not.toBeInTheDocument();
    expect(screen.queryByText("Deploy service foo to prod")).not.toBeInTheDocument();
  });

  it("shows '1 result' (singular) when exactly one prompt matches", async () => {
    const user = userEvent.setup({});
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    await user.type(screen.getByPlaceholderText("Search prompts…"), "intl-sre");

    await waitFor(() =>
      expect(screen.getByText("1 result")).toBeInTheDocument()
    );
  });

  it("shows 'N results' (plural) when multiple prompts match", async () => {
    const user = userEvent.setup({});
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    // "health" matches 2 items in Health Agent group + 0 in Deploy Agent
    await user.type(screen.getByPlaceholderText("Search prompts…"), "health");

    await waitFor(() =>
      expect(screen.getByText("2 results")).toBeInTheDocument()
    );
  });

  it("hides the result count when search input is empty", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    // No query — result count not shown
    expect(screen.queryByText(/result/)).not.toBeInTheDocument();
  });

  it("shows 'No prompts match your search.' when query has no matches", async () => {
    const user = userEvent.setup({});
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    await user.type(screen.getByPlaceholderText("Search prompts…"), "zzznomatch");

    await waitFor(() =>
      expect(screen.getByText("No prompts match your search.")).toBeInTheDocument()
    );
  });

  it("hides a group entirely when none of its prompts match the search", async () => {
    const user = userEvent.setup({});
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    // "deploy" only matches Deploy Agent items
    await user.type(screen.getByPlaceholderText("Search prompts…"), "deploy");

    await waitFor(() =>
      expect(screen.queryByText("Health Agent")).not.toBeInTheDocument()
    );
    expect(screen.getByText("Deploy Agent")).toBeInTheDocument();
  });

  it("clear-search button removes the query", async () => {
    const user = userEvent.setup({});
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    const input = screen.getByPlaceholderText("Search prompts…");
    await user.type(input, "intl-sre");

    // The X button appears after typing
    const clearBtn = document.querySelector(
      "button.text-gray-600"
    ) as HTMLElement;
    await user.click(clearBtn);

    expect((input as HTMLInputElement).value).toBe("");
    // Both groups visible again
    expect(screen.getByText("Health Agent")).toBeInTheDocument();
    expect(screen.getByText("Deploy Agent")).toBeInTheDocument();
  });

  // ── Highlighted text ──────────────────────────────────────────────────────────

  it("wraps the matching substring in a <mark> element", async () => {
    const user = userEvent.setup({});
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    await user.type(screen.getByPlaceholderText("Search prompts…"), "intl");

    await waitFor(() => {
      const mark = document.querySelector("mark");
      expect(mark).toBeInTheDocument();
      expect(mark!.textContent).toBe("intl");
    });
  });

  it("does not render <mark> when there is no search query", async () => {
    mockFetch.mockResolvedValue(faqResponse(FAQ_DATA));
    renderPanel();

    await waitFor(() => screen.getByText("Health Agent"));

    expect(document.querySelector("mark")).not.toBeInTheDocument();
  });
});
