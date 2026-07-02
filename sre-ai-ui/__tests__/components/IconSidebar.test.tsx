import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { IconSidebar } from "@/components/IconSidebar";

// ─── Context mocks ────────────────────────────────────────────────────────────
// Use jest.fn() so individual tests can call mockReturnValueOnce / mockReturnValue.

const mockToggleTheme = jest.fn();
const mockUseTheme = jest.fn(() => ({
  isDark: false,
  theme: "light",
  toggleTheme: mockToggleTheme,
}));

jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: (...args: unknown[]) => mockUseTheme(...args),
}));

// ─── AuthContext mock ─────────────────────────────────────────────────────────
// IconSidebar now calls useAuth() internally to access logout.

const mockLogout = jest.fn();
jest.mock("@/contexts/AuthContext", () => ({
  ...jest.requireActual("@/contexts/AuthContext"),
  useAuth: () => ({
    user: null,
    loading: false,
    isLoggingOut: false,
    login: jest.fn(),
    logout: mockLogout,
  }),
}));

// ─── lucide-react mock ────────────────────────────────────────────────────────
// Render lightweight SVG stubs with data-testid so icon presence can be
// asserted without caring about SVG path internals.

jest.mock("lucide-react", () => ({
  LayoutGrid: ({ className }: { className?: string }) => (
    <svg data-testid="icon-layout-grid" className={className} />
  ),
  Cloud: ({ className }: { className?: string }) => (
    <svg data-testid="icon-cloud" className={className} />
  ),
  Sun: ({ className }: { className?: string }) => (
    <svg data-testid="icon-sun" className={className} />
  ),
  Moon: ({ className }: { className?: string }) => (
    <svg data-testid="icon-moon" className={className} />
  ),
  Bell: ({ className }: { className?: string }) => (
    <svg data-testid="icon-bell" className={className} />
  ),
  Gauge: ({ className }: { className?: string }) => (
    <svg data-testid="icon-gauge" className={className} />
  ),
  ClipboardList: ({ className }: { className?: string }) => (
    <svg data-testid="icon-clipboard-list" className={className} />
  ),
}));

// ─── Helpers ──────────────────────────────────────────────────────────────────

const defaultProps = {
  activeView: "chat" as const,
  onViewChange: jest.fn(),
};

function renderSidebar(
  props: Partial<React.ComponentProps<typeof IconSidebar>> = {}
) {
  return render(<IconSidebar {...defaultProps} {...props} />);
}

// ─── Tests ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();
  // Restore default light-mode return value before each test.
  mockUseTheme.mockReturnValue({
    isDark: false,
    theme: "light",
    toggleTheme: mockToggleTheme,
  });
});

describe("IconSidebar", () => {
  describe("logo", () => {
    it("renders the SOP logo text", () => {
      renderSidebar();
      expect(screen.getByText("SOP")).toBeInTheDocument();
    });
  });

  describe("navigation items visibility", () => {
    it("renders the Applications nav item", () => {
      renderSidebar();
      expect(screen.getByText("Applications")).toBeInTheDocument();
    });

    it("renders the Managed Services nav item", () => {
      renderSidebar();
      expect(screen.getByText(/managed/i)).toBeInTheDocument();
    });

    it("renders the AI Chat button", () => {
      renderSidebar();
      expect(screen.getByText("AI Chat")).toBeInTheDocument();
    });
  });

  describe("onViewChange callbacks", () => {
    it("calls onViewChange('applications') when Applications button is clicked", () => {
      const onViewChange = jest.fn();
      renderSidebar({ onViewChange });
      fireEvent.click(screen.getByText("Applications"));
      expect(onViewChange).toHaveBeenCalledTimes(1);
      expect(onViewChange).toHaveBeenCalledWith("applications");
    });

    it("calls onViewChange('managed-services') when Managed Services button is clicked", () => {
      const onViewChange = jest.fn();
      renderSidebar({ onViewChange });
      const msButton = screen.getByText(/managed/i).closest("button");
      expect(msButton).not.toBeNull();
      fireEvent.click(msButton!);
      expect(onViewChange).toHaveBeenCalledWith("managed-services");
    });

    it("calls onViewChange('chat') when AI Chat button is clicked", () => {
      const onViewChange = jest.fn();
      renderSidebar({ onViewChange });
      const chatButton = screen.getByText("AI Chat").closest("button");
      expect(chatButton).not.toBeNull();
      fireEvent.click(chatButton!);
      expect(onViewChange).toHaveBeenCalledTimes(1);
      expect(onViewChange).toHaveBeenCalledWith("chat");
    });
  });

  describe("active item styling", () => {
    it("applies border-l-2 border-[#90EE90] class to the active Applications item", () => {
      renderSidebar({ activeView: "applications" });
      const applicationsButton = screen.getByText("Applications").closest("button");
      expect(applicationsButton).toHaveClass("border-l-2", "border-[#90EE90]");
    });

    it("applies border-l-2 border-[#90EE90] class to AI Chat button when chat is active", () => {
      renderSidebar({ activeView: "chat" });
      const chatButton = screen.getByText("AI Chat").closest("button");
      expect(chatButton).toHaveClass("border-l-2", "border-[#90EE90]");
    });

    it("applies transparent border to inactive Applications item", () => {
      renderSidebar({ activeView: "chat" });
      const applicationsButton = screen.getByText("Applications").closest("button");
      expect(applicationsButton).toHaveClass("border-transparent");
    });

    it("applies transparent border to AI Chat button when it is not active", () => {
      renderSidebar({ activeView: "applications" });
      const chatButton = screen.getByText("AI Chat").closest("button");
      expect(chatButton).toHaveClass("border-transparent");
    });

    it("applies text-[#90EE90] to the active Applications label", () => {
      renderSidebar({ activeView: "applications" });
      const label = screen.getByText("Applications");
      expect(label).toHaveClass("text-[#90EE90]");
    });

    it("applies text-white to an inactive Applications label", () => {
      renderSidebar({ activeView: "chat" });
      const label = screen.getByText("Applications");
      expect(label).toHaveClass("text-white");
    });
  });

  describe("theme toggle button — light mode (isDark=false)", () => {
    it("shows 'Switch to dark mode' title when isDark is false", () => {
      renderSidebar();
      expect(screen.getByTitle("Switch to dark mode")).toBeInTheDocument();
    });

    it("shows Moon icon when isDark is false", () => {
      renderSidebar();
      expect(screen.getByTestId("icon-moon")).toBeInTheDocument();
    });

    it("does NOT show Sun icon when isDark is false", () => {
      renderSidebar();
      expect(screen.queryByTestId("icon-sun")).not.toBeInTheDocument();
    });

    it("calls toggleTheme when the theme toggle button is clicked", () => {
      renderSidebar();
      const themeBtn = screen.getByTitle("Switch to dark mode");
      fireEvent.click(themeBtn);
      expect(mockToggleTheme).toHaveBeenCalledTimes(1);
    });
  });

  describe("theme toggle button — dark mode (isDark=true)", () => {
    beforeEach(() => {
      mockUseTheme.mockReturnValue({
        isDark: true,
        theme: "dark",
        toggleTheme: mockToggleTheme,
      });
    });

    it("shows 'Switch to light mode' title when isDark is true", () => {
      renderSidebar();
      expect(screen.getByTitle("Switch to light mode")).toBeInTheDocument();
    });

    it("shows Sun icon when isDark is true", () => {
      renderSidebar();
      expect(screen.getByTestId("icon-sun")).toBeInTheDocument();
    });

    it("does NOT show Moon icon when isDark is true", () => {
      renderSidebar();
      expect(screen.queryByTestId("icon-moon")).not.toBeInTheDocument();
    });

    it("calls toggleTheme when the theme toggle button is clicked in dark mode", () => {
      renderSidebar();
      const themeBtn = screen.getByTitle("Switch to light mode");
      fireEvent.click(themeBtn);
      expect(mockToggleTheme).toHaveBeenCalledTimes(1);
    });
  });

  describe("user avatar initial", () => {
    // The AiChatIcon SVG contains text nodes ("A", "+") that would clash with
    // certain single-letter assertions.  Scope all avatar checks to the avatar
    // <div> container to avoid false positives.

    function getAvatarEl(container: HTMLElement) {
      return container.querySelector(
        ".w-8.h-8.rounded-full"
      ) as HTMLElement;
    }

    it("shows 'U' when no userId is provided", () => {
      const { container } = renderSidebar({ userId: undefined });
      expect(getAvatarEl(container)).toHaveTextContent("U");
    });

    it("shows 'U' when userId is an empty string", () => {
      const { container } = renderSidebar({ userId: "" });
      expect(getAvatarEl(container)).toHaveTextContent("U");
    });

    it("shows 'U' for 'user@email.com' (first char of email prefix 'user')", () => {
      // getInitial("user@email.com"): namePart = "user", no dash → "U"
      const { container } = renderSidebar({ userId: "user@email.com" });
      expect(getAvatarEl(container)).toHaveTextContent("U");
    });

    it("shows 'V' for userId 'vn59z7y' (no @ or dash → charAt(0) of full id)", () => {
      // getInitial("vn59z7y"): no "@", no "-" → cleanName = "vn59z7y" → "V"
      const { container } = renderSidebar({ userId: "vn59z7y" });
      expect(getAvatarEl(container)).toHaveTextContent("V");
    });

    it("shows 'D' for hyphenated userId 'john-doe' (last segment after dash)", () => {
      // getInitial("john-doe"): has dash → cleanName = "doe" → "D"
      const { container } = renderSidebar({ userId: "john-doe" });
      expect(getAvatarEl(container)).toHaveTextContent("D");
    });

    it("shows 'D' for 'john-doe@company.com' (email with hyphenated prefix)", () => {
      // getInitial("john-doe@company.com"): namePart = "john-doe", dash → "doe" → "D"
      const { container } = renderSidebar({ userId: "john-doe@company.com" });
      expect(getAvatarEl(container)).toHaveTextContent("D");
    });

    it("shows 'B' for a plain single-word userId 'bob'", () => {
      // Uses 'bob' to avoid the SVG 'A' node inside AiChatIcon
      const { container } = renderSidebar({ userId: "bob" });
      expect(getAvatarEl(container)).toHaveTextContent("B");
    });

    it("shows 'Z' for userId 'last-z' (last segment 'z' uppercased)", () => {
      const { container } = renderSidebar({ userId: "last-z" });
      expect(getAvatarEl(container)).toHaveTextContent("Z");
    });
  });

  describe("hover interactions", () => {
    it("sets hover background on Applications button on mouseEnter", () => {
      renderSidebar({ activeView: "chat" });
      const applicationsButton = screen.getByText("Applications").closest("button")!;
      expect(applicationsButton.className).not.toContain("bg-[#1a1f2e]");

      fireEvent.mouseEnter(applicationsButton);
      expect(applicationsButton.className).toContain("bg-[#1a1f2e]");
    });

    it("removes hover background on Applications button on mouseLeave", () => {
      renderSidebar({ activeView: "chat" });
      const applicationsButton = screen.getByText("Applications").closest("button")!;
      fireEvent.mouseEnter(applicationsButton);
      expect(applicationsButton.className).toContain("bg-[#1a1f2e]");

      fireEvent.mouseLeave(applicationsButton);
      expect(applicationsButton.className).not.toContain("bg-[#1a1f2e]");
    });

    it("sets hover background on AI Chat button on mouseEnter", () => {
      renderSidebar({ activeView: "applications" });
      const chatButton = screen.getByText("AI Chat").closest("button")!;
      fireEvent.mouseEnter(chatButton);
      expect(chatButton.className).toContain("bg-[#1a1f2e]");
    });

    it("removes hover background on AI Chat button on mouseLeave", () => {
      renderSidebar({ activeView: "applications" });
      const chatButton = screen.getByText("AI Chat").closest("button")!;
      fireEvent.mouseEnter(chatButton);
      fireEvent.mouseLeave(chatButton);
      expect(chatButton.className).not.toContain("bg-[#1a1f2e]");
    });
  });
});
