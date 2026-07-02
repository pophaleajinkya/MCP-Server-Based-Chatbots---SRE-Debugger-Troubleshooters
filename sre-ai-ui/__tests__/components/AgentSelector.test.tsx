/**
 * Tests for src/components/AgentSelector.tsx
 *
 * Covers:
 *  - Shows loading state while fetching agents
 *  - Shows error state when no agents configured
 *  - Shows single agent without dropdown
 *  - Shows dropdown with multiple agents
 *  - Opens dropdown on click
 *  - Closes dropdown on outside click
 *  - Selects agent from dropdown
 *  - Auto-selects first agent if current selection not in list
 *  - Shows active badge for selected agent
 *  - Displays agent emoji, name, description, and URL
 *  - Handles fetch error gracefully
 */

import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ── Mock ThemeContext ──────────────────────────────────────────────────────────

const mockIsDark = { value: false };
jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: mockIsDark.value, theme: mockIsDark.value ? "dark" : "light", toggleTheme: jest.fn() }),
}));

import { AgentSelector } from "@/components/AgentSelector";

// ── Mock Data ─────────────────────────────────────────────────────────────────

const MOCK_AGENTS = [
  {
    id: "agent-1",
    name: "SRE Agent",
    description: "Handles SRE tasks",
    url: "https://agent1.example.com/a2a",
    emoji: "🔧",
  },
  {
    id: "agent-2",
    name: "DevOps Agent",
    description: "DevOps automation",
    url: "https://agent2.example.com/a2a",
    emoji: "🚀",
  },
  {
    id: "agent-3",
    name: "Monitoring Agent",
    description: "Metrics and alerts",
    url: "https://agent3.example.com/a2a",
    emoji: "📊",
  },
];

const SINGLE_AGENT = [MOCK_AGENTS[0]];

// ── Test Setup ────────────────────────────────────────────────────────────────

describe("AgentSelector", () => {
  const mockOnChange = jest.fn();
  const mockFetch = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = mockFetch;
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  // ── Loading State ───────────────────────────────────────────────────────────

  it("shows loading state while fetching agents", async () => {
    // Never resolves during this test
    mockFetch.mockReturnValue(new Promise(() => {}));

    render(<AgentSelector selectedId="" onChange={mockOnChange} />);

    expect(screen.getByText("Loading agents…")).toBeInTheDocument();
  });

  it("shows loading spinner icon", async () => {
    mockFetch.mockReturnValue(new Promise(() => {}));

    const { container } = render(
      <AgentSelector selectedId="" onChange={mockOnChange} />
    );

    const spinner = container.querySelector(".animate-spin");
    expect(spinner).toBeInTheDocument();
  });

  // ── Error State ─────────────────────────────────────────────────────────────

  it("shows error state when no agents configured", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: [] }),
    });

    render(<AgentSelector selectedId="" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("No agents configured")).toBeInTheDocument();
    });
  });

  it("handles fetch error gracefully", async () => {
    mockFetch.mockRejectedValueOnce(new Error("Network error"));

    render(<AgentSelector selectedId="" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("No agents configured")).toBeInTheDocument();
    });
  });

  // ── Single Agent ────────────────────────────────────────────────────────────

  it("shows single agent without dropdown", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: SINGLE_AGENT }),
    });

    render(<AgentSelector selectedId="" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("SRE Agent")).toBeInTheDocument();
    });

    // Should not have a dropdown toggle (chevron)
    expect(screen.queryByText("Select Agent")).not.toBeInTheDocument();
  });

  it("shows emoji for single agent", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: SINGLE_AGENT }),
    });

    render(<AgentSelector selectedId="" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("🔧")).toBeInTheDocument();
    });
  });

  // ── Multiple Agents Dropdown ────────────────────────────────────────────────

  it("shows selected agent name with dropdown toggle", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(<AgentSelector selectedId="agent-2" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("DevOps Agent")).toBeInTheDocument();
    });
  });

  it("opens dropdown on click", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(<AgentSelector selectedId="agent-1" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("SRE Agent")).toBeInTheDocument();
    });

    // Click the dropdown button
    const button = screen.getByRole("button");
    await user.click(button);

    expect(screen.getByText("Select Agent")).toBeInTheDocument();
    expect(screen.getByText("DevOps Agent")).toBeInTheDocument();
    expect(screen.getByText("Monitoring Agent")).toBeInTheDocument();
  });

  it("closes dropdown on outside click", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(
      <div>
        <div data-testid="outside">Outside</div>
        <AgentSelector selectedId="agent-1" onChange={mockOnChange} />
      </div>
    );

    await waitFor(() => {
      expect(screen.getByText("SRE Agent")).toBeInTheDocument();
    });

    // Open dropdown
    const button = screen.getByRole("button");
    await user.click(button);
    expect(screen.getByText("Select Agent")).toBeInTheDocument();

    // Click outside
    await user.click(screen.getByTestId("outside"));

    await waitFor(() => {
      expect(screen.queryByText("Select Agent")).not.toBeInTheDocument();
    });
  });

  it("closes dropdown on second click of button", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(<AgentSelector selectedId="agent-1" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("SRE Agent")).toBeInTheDocument();
    });

    const button = screen.getByRole("button");
    
    // Open
    await user.click(button);
    expect(screen.getByText("Select Agent")).toBeInTheDocument();

    // Close
    await user.click(button);
    await waitFor(() => {
      expect(screen.queryByText("Select Agent")).not.toBeInTheDocument();
    });
  });

  // ── Agent Selection ─────────────────────────────────────────────────────────

  it("calls onChange when agent is selected", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(<AgentSelector selectedId="agent-1" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("SRE Agent")).toBeInTheDocument();
    });

    // Open dropdown
    await user.click(screen.getByRole("button"));

    // Select different agent
    const agentOptions = screen.getAllByRole("button");
    const devOpsOption = agentOptions.find((btn) =>
      btn.textContent?.includes("DevOps Agent")
    );
    await user.click(devOpsOption!);

    expect(mockOnChange).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "agent-2",
        name: "DevOps Agent",
      })
    );
  });

  it("closes dropdown after selection", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(<AgentSelector selectedId="agent-1" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("SRE Agent")).toBeInTheDocument();
    });

    // Open dropdown
    await user.click(screen.getByRole("button"));
    expect(screen.getByText("Select Agent")).toBeInTheDocument();

    // Select agent
    const agentOptions = screen.getAllByRole("button");
    const devOpsOption = agentOptions.find((btn) =>
      btn.textContent?.includes("DevOps Agent")
    );
    await user.click(devOpsOption!);

    await waitFor(() => {
      expect(screen.queryByText("Select Agent")).not.toBeInTheDocument();
    });
  });

  // ── Auto-Selection ──────────────────────────────────────────────────────────

  it("auto-selects first agent if selectedId not in list", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(
      <AgentSelector selectedId="non-existent-id" onChange={mockOnChange} />
    );

    await waitFor(() => {
      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({ id: "agent-1" })
      );
    });
  });

  it("does not auto-select when selectedId is in list", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(<AgentSelector selectedId="agent-2" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("DevOps Agent")).toBeInTheDocument();
    });

    // Should not trigger onChange for auto-selection
    expect(mockOnChange).not.toHaveBeenCalled();
  });

  // ── Active Badge ────────────────────────────────────────────────────────────

  it("shows ACTIVE badge for selected agent in dropdown", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(<AgentSelector selectedId="agent-1" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("SRE Agent")).toBeInTheDocument();
    });

    // Open dropdown
    await user.click(screen.getByRole("button"));

    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
  });

  // ── Agent Details ───────────────────────────────────────────────────────────

  it("displays agent description in dropdown", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(<AgentSelector selectedId="agent-1" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("SRE Agent")).toBeInTheDocument();
    });

    // Open dropdown
    await user.click(screen.getByRole("button"));

    expect(screen.getByText("Handles SRE tasks")).toBeInTheDocument();
    expect(screen.getByText("DevOps automation")).toBeInTheDocument();
  });

  it("displays agent URL in dropdown", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(<AgentSelector selectedId="agent-1" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("SRE Agent")).toBeInTheDocument();
    });

    // Open dropdown
    await user.click(screen.getByRole("button"));

    // URL should have https:// and /a2a stripped
    expect(screen.getByText("agent1.example.com")).toBeInTheDocument();
  });

  it("displays agent emojis in dropdown", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    render(<AgentSelector selectedId="agent-1" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("🔧")).toBeInTheDocument();
    });

    // Open dropdown
    await user.click(screen.getByRole("button"));

    expect(screen.getByText("🚀")).toBeInTheDocument();
    expect(screen.getByText("📊")).toBeInTheDocument();
  });

  // ── Default Values ──────────────────────────────────────────────────────────

  it("uses default emoji when agent has no emoji", async () => {
    const agentsNoEmoji = [{ ...MOCK_AGENTS[0], emoji: undefined }];
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: agentsNoEmoji }),
    });

    render(<AgentSelector selectedId="" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("🤖")).toBeInTheDocument();
    });
  });

  it("uses default name when agent has no name", async () => {
    const agentsNoName = [{ ...MOCK_AGENTS[0], name: undefined }];
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: agentsNoName }),
    });

    render(<AgentSelector selectedId="" onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText("Agent")).toBeInTheDocument();
    });
  });

  // ── Dark mode variants ───────────────────────────────────────────────────────

  describe("dark mode", () => {
    beforeEach(() => { mockIsDark.value = true; });
    afterEach(() => { mockIsDark.value = false; });

    it("loading state applies dark class", async () => {
      mockFetch.mockReturnValue(new Promise(() => {})); // pending
      const { container } = render(
        <AgentSelector selectedId="" onChange={mockOnChange} />
      );
      // Loading spinner div should have dark border/bg class
      expect(container.querySelector(".border-gray-700\\/50")).toBeInTheDocument();
    });

    it("empty agents state applies dark class", async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ agents: [] }) });
      const { container } = render(
        <AgentSelector selectedId="" onChange={mockOnChange} />
      );
      await waitFor(() => {
        expect(container.querySelector(".text-red-400")).toBeInTheDocument();
      });
    });

    it("single agent applies dark class", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ agents: [MOCK_AGENTS[0]] }),
      });
      const { container } = render(
        <AgentSelector selectedId="agent-1" onChange={mockOnChange} />
      );
      await waitFor(() => {
        expect(container.querySelector(".text-gray-300")).toBeInTheDocument();
      });
    });

    it("multi-agent dropdown button applies dark class", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ agents: MOCK_AGENTS }),
      });
      const { container } = render(
        <AgentSelector selectedId="agent-1" onChange={mockOnChange} />
      );
      await waitFor(() => screen.getByText("SRE Agent"));
      // Main button should have dark background class
      const btn = screen.getByRole("button");
      expect(btn.className).toContain("bg-gray-800");
    });
  });

  // ── Chevron Rotation ────────────────────────────────────────────────────────

  it("rotates chevron when dropdown is open", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ agents: MOCK_AGENTS }),
    });

    const { container } = render(
      <AgentSelector selectedId="agent-1" onChange={mockOnChange} />
    );

    await waitFor(() => {
      expect(screen.getByText("SRE Agent")).toBeInTheDocument();
    });

    // Find chevron icon by class
    let chevron = container.querySelector(".transition-transform");
    expect(chevron).toBeInTheDocument();

    // Open dropdown
    await user.click(screen.getByRole("button"));

    // After opening, chevron should have rotate class
    chevron = container.querySelector(".transition-transform");
    expect(chevron?.classList.contains("rotate-180")).toBe(true);
  });
});
