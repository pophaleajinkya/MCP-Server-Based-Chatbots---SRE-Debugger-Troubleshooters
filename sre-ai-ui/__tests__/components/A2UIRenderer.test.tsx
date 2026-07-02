import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { A2UIRenderer } from "@/components/A2UIRenderer";

// MarkdownRenderer is used inside A2UIRenderer for multi-line text
jest.mock("@/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="markdown-renderer">{content}</div>
  ),
}));

// recharts is already mocked in jest.setup.ts but we need PieChart + Cell too
// Legend renders a clickable element so we can test toggleSeries via onClick
jest.mock("recharts", () => {
  const React = require("react");
  const stub =
    (testId?: string) =>
    ({ children, ...props }: { children?: React.ReactNode; [k: string]: unknown }) =>
      React.createElement("div", { "data-testid": testId ?? "recharts-stub" }, children);
  return {
    __esModule: true,
    ResponsiveContainer: stub("recharts-responsive-container"),
    LineChart: stub("recharts-line-chart"),
    BarChart: stub("recharts-bar-chart"),
    AreaChart: stub("recharts-area-chart"),
    PieChart: stub("recharts-pie-chart"),
    Pie: stub("recharts-pie"),
    Cell: () => null,
    Line: () => null,
    Bar: () => null,
    Area: () => null,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
    Legend: ({ onClick, ...props }: { onClick?: (e: unknown) => void; [k: string]: unknown }) =>
      React.createElement(
        "div",
        {
          "data-testid": "recharts-legend",
          onClick: () => onClick?.({ dataKey: "Series A" }),
        },
        "Legend"
      ),
  };
});

// Helper: wrap a single component in A2UI message format
function makeMsg(components: Record<string, unknown>[]) {
  return {
    updateComponents: {
      surfaceId: "test-surface",
      components: components.map((c, i) => ({ id: `c${i}`, ...c })),
    },
  };
}

// Helper: wrap multiple components with explicit IDs
function makeMsgWithIds(components: Array<{ id: string; [k: string]: unknown }>) {
  return {
    updateComponents: {
      surfaceId: "test-surface",
      components,
    },
  };
}

// ---------------------------------------------------------------------------
// Basic rendering / empty data
// ---------------------------------------------------------------------------

describe("A2UIRenderer", () => {
  describe("basic rendering", () => {
    it("renders empty when data has no updateComponents", () => {
      const { container } = render(<A2UIRenderer data={{}} />);
      expect(container.querySelector(".a2ui-root")).toBeInTheDocument();
    });

    it("renders empty when components array is empty", () => {
      const { container } = render(
        <A2UIRenderer data={{ updateComponents: { components: [] } }} />
      );
      expect(container.querySelector(".a2ui-root")).toBeInTheDocument();
    });

    it("handles array of messages", () => {
      const data = [
        makeMsg([{ component: "Text", text: "Message 1" }]),
        makeMsg([{ component: "Text", text: "Message 2" }]),
      ];
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Message 1")).toBeInTheDocument();
      expect(screen.getByText("Message 2")).toBeInTheDocument();
    });
  });

  // ─── Layout components ──────────────────────────────────────────────────

  describe("Row", () => {
    it("renders children horizontally", () => {
      const data = makeMsgWithIds([
        { id: "row", component: "Row", children: ["t1", "t2"] },
        { id: "t1", component: "Text", text: "Left" },
        { id: "t2", component: "Text", text: "Right" },
      ]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Left")).toBeInTheDocument();
      expect(screen.getByText("Right")).toBeInTheDocument();
    });

    it("applies justify and align classes", () => {
      const data = makeMsgWithIds([
        { id: "row", component: "Row", children: ["t1"], justify: "center", align: "end" },
        { id: "t1", component: "Text", text: "Centered" },
      ]);
      const { container } = render(<A2UIRenderer data={data} />);
      const rowDiv = container.querySelector(".flex.flex-row");
      expect(rowDiv?.className).toContain("justify-center");
      expect(rowDiv?.className).toContain("items-end");
    });
  });

  describe("Column", () => {
    it("renders children vertically", () => {
      const data = makeMsgWithIds([
        { id: "col", component: "Column", children: ["t1"] },
        { id: "t1", component: "Text", text: "Column child" },
      ]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Column child")).toBeInTheDocument();
    });

    it("applies justify and align classes", () => {
      const data = makeMsgWithIds([
        { id: "col", component: "Column", children: ["t1"], justify: "spaceBetween", align: "center" },
        { id: "t1", component: "Text", text: "Hi" },
      ]);
      const { container } = render(<A2UIRenderer data={data} />);
      const colDiv = container.querySelector(".justify-between.items-center");
      expect(colDiv).toBeInTheDocument();
      expect(colDiv?.className).toContain("flex");
      expect(colDiv?.className).toContain("flex-col");
    });
  });

  describe("List", () => {
    it("renders vertical list by default", () => {
      const data = makeMsgWithIds([
        { id: "list", component: "List", children: ["t1"] },
        { id: "t1", component: "Text", text: "Item" },
      ]);
      const { container } = render(<A2UIRenderer data={data} />);
      expect(container.querySelector(".flex.flex-col.gap-1")).toBeInTheDocument();
      expect(screen.getByText("Item")).toBeInTheDocument();
    });

    it("renders horizontal list when direction is horizontal", () => {
      const data = makeMsgWithIds([
        { id: "list", component: "List", children: ["t1"], direction: "horizontal" },
        { id: "t1", component: "Text", text: "Item" },
      ]);
      const { container } = render(<A2UIRenderer data={data} />);
      expect(container.querySelector(".flex.flex-row.gap-2")).toBeInTheDocument();
    });
  });

  // ─── Display components ─────────────────────────────────────────────────

  describe("Text", () => {
    it("renders body text by default", () => {
      const data = makeMsg([{ component: "Text", text: "Hello world" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Hello world")).toBeInTheDocument();
    });

    it("renders heading variants", () => {
      for (const variant of ["h1", "h2", "h3", "h4", "h5"]) {
        const data = makeMsg([{ component: "Text", text: `Heading ${variant}`, variant }]);
        const { unmount } = render(<A2UIRenderer data={data} />);
        expect(screen.getByText(`Heading ${variant}`)).toBeInTheDocument();
        unmount();
      }
    });

    it("renders caption variant", () => {
      const data = makeMsg([{ component: "Text", text: "Caption text", variant: "caption" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      // caption uses inline markdown (dangerouslySetInnerHTML), so check the p tag
      const p = container.querySelector("p");
      expect(p?.textContent).toBe("Caption text");
    });

    it("uses MarkdownRenderer for multi-line text", () => {
      const data = makeMsg([{ component: "Text", text: "Line1\nLine2" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByTestId("markdown-renderer")).toBeInTheDocument();
    });

    it("uses MarkdownRenderer for text starting with #", () => {
      const data = makeMsg([{ component: "Text", text: "# Heading" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByTestId("markdown-renderer")).toBeInTheDocument();
    });

    it("renders inline markdown (bold, italic, code, link)", () => {
      const data = makeMsg([{ component: "Text", text: "Hello **bold** and *italic* and `code` and [link](http://example.com)" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      const p = container.querySelector("p");
      expect(p?.innerHTML).toContain("<strong>");
      expect(p?.innerHTML).toContain("<em>");
      expect(p?.innerHTML).toContain("<code");
      expect(p?.innerHTML).toContain("<a ");
    });

    it("handles empty text gracefully", () => {
      const data = makeMsg([{ component: "Text" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      // Should still render something without crashing
      expect(container.querySelector(".a2ui-root")).toBeInTheDocument();
    });
  });

  describe("Image", () => {
    it("renders an image with src and alt", () => {
      const data = makeMsg([{ component: "Image", url: "https://example.com/img.png", alt: "Example" }]);
      render(<A2UIRenderer data={data} />);
      const img = screen.getByRole("img");
      expect(img).toHaveAttribute("src", "https://example.com/img.png");
      expect(img).toHaveAttribute("alt", "Example");
    });

    it("returns null when no url is provided", () => {
      const data = makeMsg([{ component: "Image" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      expect(container.querySelector("img")).not.toBeInTheDocument();
    });

    it("applies cover fit class", () => {
      const data = makeMsg([{ component: "Image", url: "https://example.com/img.png", fit: "cover", alt: "cover-img" }]);
      render(<A2UIRenderer data={data} />);
      const img = screen.getByAltText("cover-img");
      expect(img.className).toContain("object-cover");
    });

    it("applies contain fit class by default", () => {
      const data = makeMsg([{ component: "Image", url: "https://example.com/img.png", alt: "contain-img" }]);
      render(<A2UIRenderer data={data} />);
      const img = screen.getByAltText("contain-img");
      expect(img.className).toContain("object-contain");
    });
  });

  describe("Icon", () => {
    it("renders known icon (check)", () => {
      const data = makeMsg([{ component: "Icon", name: "check" }]);
      render(<A2UIRenderer data={data} />);
      const icon = screen.getByRole("img", { name: "check" });
      expect(icon).toBeInTheDocument();
      expect(icon.querySelector("svg")).toBeInTheDocument();
    });

    it("renders known icon (warning)", () => {
      const data = makeMsg([{ component: "Icon", name: "warning" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByRole("img", { name: "warning" })).toBeInTheDocument();
    });

    it("renders known icon (error)", () => {
      const data = makeMsg([{ component: "Icon", name: "error" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByRole("img", { name: "error" })).toBeInTheDocument();
    });

    it("renders known icon (info)", () => {
      const data = makeMsg([{ component: "Icon", name: "info" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByRole("img", { name: "info" })).toBeInTheDocument();
    });

    it("renders known icon (search)", () => {
      const data = makeMsg([{ component: "Icon", name: "search" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByRole("img", { name: "search" })).toBeInTheDocument();
    });

    it("renders known icon (close)", () => {
      const data = makeMsg([{ component: "Icon", name: "close" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByRole("img", { name: "close" })).toBeInTheDocument();
    });

    it("renders known icon (settings)", () => {
      const data = makeMsg([{ component: "Icon", name: "settings" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByRole("img", { name: "settings" })).toBeInTheDocument();
    });

    it("renders known icon (star)", () => {
      const data = makeMsg([{ component: "Icon", name: "star" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByRole("img", { name: "star" })).toBeInTheDocument();
    });

    it("renders unknown icon as text", () => {
      const data = makeMsg([{ component: "Icon", name: "unknown-icon" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("unknown-icon")).toBeInTheDocument();
    });
  });

  describe("Divider", () => {
    it("renders a horizontal divider by default", () => {
      const data = makeMsg([{ component: "Divider" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      expect(container.querySelector("hr")).toBeInTheDocument();
    });

    it("renders a vertical divider when axis is vertical", () => {
      const data = makeMsg([{ component: "Divider", axis: "vertical" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      const hr = container.querySelector("hr");
      expect(hr?.className).toContain("border-l");
    });
  });

  // ─── Interactive components ─────────────────────────────────────────────

  describe("Button", () => {
    it("renders a button with child text", () => {
      const data = makeMsgWithIds([
        { id: "btn", component: "Button", child: "label", action: { event: { data: { url: "http://example.com" } } } },
        { id: "label", component: "Text", text: "Click me", variant: "body" },
      ]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Click me")).toBeInTheDocument();
      const link = screen.getByRole("link");
      expect(link).toHaveAttribute("href", "http://example.com");
      expect(link).toHaveAttribute("target", "_blank");
    });

    it("renders default Button text when no child", () => {
      const data = makeMsg([{ component: "Button" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Button")).toBeInTheDocument();
    });

    it("uses # as href when no url in action", () => {
      const data = makeMsg([{ component: "Button", action: {} }]);
      render(<A2UIRenderer data={data} />);
      const link = screen.getByRole("link");
      expect(link).toHaveAttribute("href", "#");
    });

    it("applies secondary variant styling", () => {
      const data = makeMsg([{ component: "Button", variant: "secondary" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      const link = container.querySelector("a");
      expect(link?.className).toContain("border");
    });

    it("applies danger variant styling", () => {
      const data = makeMsg([{ component: "Button", variant: "danger" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      const link = container.querySelector("a");
      expect(link?.className).toContain("bg-red-600");
    });

    it("applies outlined variant styling", () => {
      const data = makeMsg([{ component: "Button", variant: "outlined" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      const link = container.querySelector("a");
      expect(link?.className).toContain("border");
    });

    it("applies destructive variant styling", () => {
      const data = makeMsg([{ component: "Button", variant: "destructive" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      const link = container.querySelector("a");
      expect(link?.className).toContain("bg-red-600");
    });
  });

  describe("TextField", () => {
    it("renders a short text input by default", () => {
      const data = makeMsg([{ component: "TextField", label: "Name", placeholder: "Enter name", value: "John" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Name")).toBeInTheDocument();
      const input = screen.getByDisplayValue("John") as HTMLInputElement;
      expect(input.type).toBe("text");
      expect(input.placeholder).toBe("Enter name");
    });

    it("renders a textarea for longText type", () => {
      const data = makeMsg([{ component: "TextField", label: "Bio", textFieldType: "longText", value: "My bio" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByDisplayValue("My bio")).toBeInstanceOf(HTMLTextAreaElement);
    });

    it("renders number input for number type", () => {
      const data = makeMsg([{ component: "TextField", textFieldType: "number" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      const input = container.querySelector("input") as HTMLInputElement;
      expect(input.type).toBe("number");
    });

    it("renders password input for obscured type", () => {
      const data = makeMsg([{ component: "TextField", textFieldType: "obscured" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      const input = container.querySelector("input") as HTMLInputElement;
      expect(input.type).toBe("password");
    });

    it("renders without label", () => {
      const data = makeMsg([{ component: "TextField" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      expect(container.querySelector("label")).not.toBeInTheDocument();
    });
  });

  describe("CheckBox", () => {
    it("renders a checkbox with label", () => {
      const data = makeMsg([{ component: "CheckBox", label: "Accept terms", value: true }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Accept terms")).toBeInTheDocument();
      const cb = screen.getByRole("checkbox") as HTMLInputElement;
      expect(cb.defaultChecked).toBe(true);
    });

    it("renders unchecked checkbox by default", () => {
      const data = makeMsg([{ component: "CheckBox", label: "Option" }]);
      render(<A2UIRenderer data={data} />);
      const cb = screen.getByRole("checkbox") as HTMLInputElement;
      expect(cb.defaultChecked).toBe(false);
    });
  });

  describe("Slider", () => {
    it("renders a range input", () => {
      const data = makeMsg([{ component: "Slider", label: "Volume", minValue: 0, maxValue: 100, value: 50 }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Volume")).toBeInTheDocument();
      const slider = screen.getByRole("slider") as HTMLInputElement;
      expect(slider.min).toBe("0");
      expect(slider.max).toBe("100");
      expect(slider.defaultValue).toBe("50");
    });

    it("renders without label", () => {
      const data = makeMsg([{ component: "Slider" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      expect(container.querySelector("label")).not.toBeInTheDocument();
      expect(screen.getByRole("slider")).toBeInTheDocument();
    });
  });

  describe("DateTimeInput", () => {
    it("renders date input by default", () => {
      const data = makeMsg([{ component: "DateTimeInput", label: "Start date" }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Start date")).toBeInTheDocument();
      const input = screen.getByDisplayValue("") as HTMLInputElement;
      expect(input.type).toBe("date");
    });

    it("renders time input when only enableTime is true", () => {
      const data = makeMsg([{ component: "DateTimeInput", enableDate: false, enableTime: true }]);
      const { container } = render(<A2UIRenderer data={data} />);
      const input = container.querySelector("input") as HTMLInputElement;
      expect(input.type).toBe("time");
    });

    it("renders datetime-local input when both date and time are enabled", () => {
      const data = makeMsg([{ component: "DateTimeInput", enableDate: true, enableTime: true }]);
      const { container } = render(<A2UIRenderer data={data} />);
      const input = container.querySelector("input") as HTMLInputElement;
      expect(input.type).toBe("datetime-local");
    });

    it("renders without label", () => {
      const data = makeMsg([{ component: "DateTimeInput" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      expect(container.querySelector("label")).not.toBeInTheDocument();
    });
  });

  describe("ChoicePicker", () => {
    it("renders select with string options", () => {
      const data = makeMsg([{ component: "ChoicePicker", label: "Color", options: ["Red", "Blue"] }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Color")).toBeInTheDocument();
      expect(screen.getByText("Red")).toBeInTheDocument();
      expect(screen.getByText("Blue")).toBeInTheDocument();
    });

    it("renders select with object options", () => {
      const data = makeMsg([{
        component: "ChoicePicker",
        options: [{ label: "Red", value: "r" }, { label: "Blue", value: "b" }],
      }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Red")).toBeInTheDocument();
      expect(screen.getByText("Blue")).toBeInTheDocument();
    });

    it("renders multi-select when maxAllowedSelections > 1", () => {
      const data = makeMsg([{ component: "ChoicePicker", options: ["A", "B"], maxAllowedSelections: 3 }]);
      const { container } = render(<A2UIRenderer data={data} />);
      const select = container.querySelector("select");
      expect(select?.multiple).toBe(true);
    });

    it("renders placeholder option for single select", () => {
      const data = makeMsg([{ component: "ChoicePicker", options: ["A"] }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Select...")).toBeInTheDocument();
    });

    it("does not render placeholder for multi-select", () => {
      const data = makeMsg([{ component: "ChoicePicker", options: ["A"], maxAllowedSelections: 2 }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.queryByText("Select...")).not.toBeInTheDocument();
    });
  });

  // ─── Container components ───────────────────────────────────────────────

  describe("Card", () => {
    it("renders card with child component", () => {
      const data = makeMsgWithIds([
        { id: "card", component: "Card", child: "text1" },
        { id: "text1", component: "Text", text: "Card content" },
      ]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Card content")).toBeInTheDocument();
    });

    it("renders card with children components", () => {
      const data = makeMsgWithIds([
        { id: "card", component: "Card", children: ["t1", "t2"] },
        { id: "t1", component: "Text", text: "First" },
        { id: "t2", component: "Text", text: "Second" },
      ]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("First")).toBeInTheDocument();
      expect(screen.getByText("Second")).toBeInTheDocument();
    });

    it("renders empty card when no child or children", () => {
      const data = makeMsg([{ component: "Card" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      expect(container.querySelector(".rounded-lg.border.p-4")).toBeInTheDocument();
    });
  });

  describe("Modal", () => {
    it("renders entry point and opens modal on click", () => {
      const data = makeMsgWithIds([
        { id: "modal", component: "Modal", entryPointChild: "trigger", contentChild: "content" },
        { id: "trigger", component: "Text", text: "Open Modal" },
        { id: "content", component: "Text", text: "Modal Content" },
      ]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Open Modal")).toBeInTheDocument();
      expect(screen.queryByText("Modal Content")).not.toBeInTheDocument();

      fireEvent.click(screen.getByText("Open Modal"));
      expect(screen.getByText("Modal Content")).toBeInTheDocument();
    });

    it("closes modal when Close button is clicked", () => {
      const data = makeMsgWithIds([
        { id: "modal", component: "Modal", entryPointChild: "trigger", contentChild: "content" },
        { id: "trigger", component: "Text", text: "Open" },
        { id: "content", component: "Text", text: "Content" },
      ]);
      render(<A2UIRenderer data={data} />);
      fireEvent.click(screen.getByText("Open"));
      expect(screen.getByText("Content")).toBeInTheDocument();
      fireEvent.click(screen.getByText("Close"));
      expect(screen.queryByText("Content")).not.toBeInTheDocument();
    });

    it("closes modal when backdrop is clicked", () => {
      const data = makeMsgWithIds([
        { id: "modal", component: "Modal", entryPointChild: "trigger", contentChild: "content" },
        { id: "trigger", component: "Text", text: "Open" },
        { id: "content", component: "Text", text: "Content" },
      ]);
      render(<A2UIRenderer data={data} />);
      fireEvent.click(screen.getByText("Open"));
      // Click the backdrop (fixed inset-0)
      const backdrop = screen.getByText("Content").closest(".bg-white, .dark\\:bg-\\[\\#1a2233\\]")?.parentElement;
      if (backdrop) fireEvent.click(backdrop);
      expect(screen.queryByText("Content")).not.toBeInTheDocument();
    });
  });

  describe("Tabs", () => {
    it("renders tabs and shows first tab content by default", () => {
      const data = makeMsgWithIds([
        { id: "tabs", component: "Tabs", tabItems: [
          { title: "Tab A", child: "contentA" },
          { title: "Tab B", child: "contentB" },
        ]},
        { id: "contentA", component: "Text", text: "Content A" },
        { id: "contentB", component: "Text", text: "Content B" },
      ]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Tab A")).toBeInTheDocument();
      expect(screen.getByText("Tab B")).toBeInTheDocument();
      expect(screen.getByText("Content A")).toBeInTheDocument();
      expect(screen.queryByText("Content B")).not.toBeInTheDocument();
    });

    it("switches tab on click", () => {
      const data = makeMsgWithIds([
        { id: "tabs", component: "Tabs", tabItems: [
          { title: "Tab A", child: "contentA" },
          { title: "Tab B", child: "contentB" },
        ]},
        { id: "contentA", component: "Text", text: "Content A" },
        { id: "contentB", component: "Text", text: "Content B" },
      ]);
      render(<A2UIRenderer data={data} />);
      fireEvent.click(screen.getByText("Tab B"));
      expect(screen.getByText("Content B")).toBeInTheDocument();
      expect(screen.queryByText("Content A")).not.toBeInTheDocument();
    });

    it("returns null when no tabItems", () => {
      const data = makeMsg([{ component: "Tabs" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      // Tabs with no tabItems renders nothing
      const root = container.querySelector(".a2ui-root");
      expect(root?.children.length).toBeLessThanOrEqual(1);
    });

    it("shows fallback when tab child is not found", () => {
      const data = makeMsgWithIds([
        { id: "tabs", component: "Tabs", tabItems: [
          { title: "Tab A", child: "missing" },
        ]},
      ]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("No content for this tab.")).toBeInTheDocument();
    });
  });

  // ─── Custom extensions ──────────────────────────────────────────────────

  describe("Table", () => {
    it("renders a table with columns and rows", () => {
      const data = makeMsg([{
        component: "Table",
        columns: ["Name", "Age"],
        rows: [["Alice", "30"], ["Bob", "25"]],
      }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Name")).toBeInTheDocument();
      expect(screen.getByText("Age")).toBeInTheDocument();
      expect(screen.getByText("Alice")).toBeInTheDocument();
      expect(screen.getByText("30")).toBeInTheDocument();
    });

    it("returns null when both columns and rows are empty", () => {
      const data = makeMsg([{ component: "Table", columns: [], rows: [] }]);
      const { container } = render(<A2UIRenderer data={data} />);
      expect(container.querySelector("table")).not.toBeInTheDocument();
    });

    it("auto-generates column headers from row data", () => {
      const data = makeMsg([{
        component: "Table",
        rows: [["Alice", "30"], ["Bob", "25"]],
      }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Col 1")).toBeInTheDocument();
      expect(screen.getByText("Col 2")).toBeInTheDocument();
    });

    it("formats special cell values as dash", () => {
      const data = makeMsg([{
        component: "Table",
        columns: ["Value"],
        rows: [["null"], ["undefined"], ["None"], ["\u2014"]],
      }]);
      render(<A2UIRenderer data={data} />);
      // All special values should be rendered as "\u2014"
      const cells = screen.getAllByText("\u2014");
      expect(cells.length).toBe(4);
    });

    it("handles non-array row values", () => {
      const data = makeMsg([{
        component: "Table",
        columns: ["Value"],
        rows: [["simple"]],
      }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("simple")).toBeInTheDocument();
    });
  });

  describe("Chart - Line/Area/Bar", () => {
    const chartData = {
      component: "Chart",
      chartType: "line",
      title: "Test Chart",
      xAxis: { labels: ["Jan", "Feb", "Mar"] },
      series: [{ label: "Series A", data: [10, 20, 30] }],
    };

    it("renders a line chart", () => {
      const data = makeMsg([chartData]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Test Chart")).toBeInTheDocument();
      expect(screen.getByTestId("recharts-responsive-container")).toBeInTheDocument();
    });

    it("shows no data message when labels are empty", () => {
      const data = makeMsg([{ ...chartData, xAxis: { labels: [] } }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Test Chart (no data)")).toBeInTheDocument();
    });

    it("returns null when no title and no data", () => {
      const data = makeMsg([{ component: "Chart", chartType: "line", xAxis: { labels: [] }, series: [] }]);
      const { container } = render(<A2UIRenderer data={data} />);
      expect(container.querySelector(".rounded-lg")).not.toBeInTheDocument();
    });

    it("switches chart type via buttons", () => {
      const data = makeMsg([chartData]);
      render(<A2UIRenderer data={data} />);
      // Click "Bar" button
      fireEvent.click(screen.getByText("Bar"));
      expect(screen.getByTestId("recharts-responsive-container")).toBeInTheDocument();
      // Click "Area" button
      fireEvent.click(screen.getByText("Area"));
      expect(screen.getByTestId("recharts-responsive-container")).toBeInTheDocument();
      // Click "Line" button
      fireEvent.click(screen.getByText("Line"));
      expect(screen.getByTestId("recharts-responsive-container")).toBeInTheDocument();
    });

    it("opens fullscreen and closes it", () => {
      const data = makeMsg([chartData]);
      render(<A2UIRenderer data={data} />);
      // Click "Full screen" button
      const fsBtn = screen.getByTitle("Full screen");
      fireEvent.click(fsBtn);
      // Fullscreen overlay should be present - there should be a Close button
      const closeBtn = screen.getByTitle("Close");
      expect(closeBtn).toBeInTheDocument();
      fireEvent.click(closeBtn);
    });

    it("renders multiple series with legend hint", () => {
      const multiSeriesData = {
        ...chartData,
        series: [
          { label: "Series A", data: [10, 20, 30] },
          { label: "Series B", data: [5, 15, 25] },
        ],
      };
      const data = makeMsg([multiSeriesData]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Click legend to show/hide series")).toBeInTheDocument();
    });

    it("toggles series visibility via legend click and resets", () => {
      const multiSeriesData = {
        ...chartData,
        series: [
          { label: "Series A", data: [10, 20, 30] },
          { label: "Series B", data: [5, 15, 25] },
        ],
      };
      const data = makeMsg([multiSeriesData]);
      render(<A2UIRenderer data={data} />);
      // Legend mock fires onClick with { dataKey: "Series A" }
      const legends = screen.getAllByTestId("recharts-legend");
      fireEvent.click(legends[0]);
      // After hiding a series, the Reset button should appear
      expect(screen.getByText("Reset")).toBeInTheDocument();
      // Click Reset to show all series again
      fireEvent.click(screen.getByText("Reset"));
      expect(screen.queryByText("Reset")).not.toBeInTheDocument();
    });

    it("toggles series off then back on via legend click", () => {
      const multiSeriesData = {
        ...chartData,
        series: [
          { label: "Series A", data: [10, 20, 30] },
          { label: "Series B", data: [5, 15, 25] },
        ],
      };
      const data = makeMsg([multiSeriesData]);
      render(<A2UIRenderer data={data} />);
      const legends = screen.getAllByTestId("recharts-legend");
      // Toggle off
      fireEvent.click(legends[0]);
      expect(screen.getByText("Reset")).toBeInTheDocument();
      // Toggle back on (same legend click)
      fireEvent.click(legends[0]);
    });

    it("closes fullscreen when backdrop is clicked", () => {
      const data = makeMsg([chartData]);
      const { container } = render(<A2UIRenderer data={data} />);
      fireEvent.click(screen.getByTitle("Full screen"));
      // Click the backdrop overlay
      const overlay = container.querySelector(".fixed.inset-0.z-50");
      if (overlay) fireEvent.click(overlay);
    });
  });

  describe("Chart - Pie", () => {
    const pieData = {
      component: "Chart",
      chartType: "pie",
      title: "Pie Chart",
      series: [{ data: [{ name: "A", value: 10 }, { name: "B", value: 20 }] }],
    };

    it("renders a pie chart", () => {
      const data = makeMsg([pieData]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Pie Chart")).toBeInTheDocument();
    });

    it("shows no data message when pie has no data", () => {
      const data = makeMsg([{ component: "Chart", chartType: "pie", title: "Empty Pie", series: [] }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Empty Pie (no data)")).toBeInTheDocument();
    });

    it("returns null when no title and no pie data", () => {
      const data = makeMsg([{ component: "Chart", chartType: "pie", series: [] }]);
      const { container } = render(<A2UIRenderer data={data} />);
      // Should render nothing for titleless empty pie
      expect(container.querySelector(".rounded-lg")).not.toBeInTheDocument();
    });

    it("opens fullscreen for pie chart and closes it", () => {
      const data = makeMsg([pieData]);
      render(<A2UIRenderer data={data} />);
      fireEvent.click(screen.getByTitle("Full screen"));
      expect(screen.getByText("Close")).toBeInTheDocument();
      fireEvent.click(screen.getByText("Close"));
    });

    it("closes pie fullscreen when backdrop is clicked", () => {
      const data = makeMsg([pieData]);
      const { container } = render(<A2UIRenderer data={data} />);
      fireEvent.click(screen.getByTitle("Full screen"));
      const overlay = container.querySelector(".fixed.inset-0.z-50");
      if (overlay) fireEvent.click(overlay);
    });

    it("handles series with invalid data format", () => {
      const data = makeMsg([{
        component: "Chart",
        chartType: "pie",
        title: "Bad Pie",
        series: [{ data: [1, 2, 3] }],  // No name field
      }]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Bad Pie (no data)")).toBeInTheDocument();
    });
  });

  // ─── Unknown / fallback components ──────────────────────────────────────

  describe("Unknown component", () => {
    it("renders children in a labeled container for unknown component", () => {
      const data = makeMsgWithIds([
        { id: "unk", component: "CustomWidget", children: ["t1"] },
        { id: "t1", component: "Text", text: "Child content" },
      ]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("CustomWidget")).toBeInTheDocument();
      expect(screen.getByText("Child content")).toBeInTheDocument();
    });

    it("renders singleChild for unknown component without children array", () => {
      const data = makeMsgWithIds([
        { id: "unk", component: "CustomWidget", child: "t1" },
        { id: "t1", component: "Text", text: "Child content" },
      ]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Child content")).toBeInTheDocument();
    });

    it("returns null for unknown component with no children", () => {
      const data = makeMsg([{ component: "CustomWidget" }]);
      const { container } = render(<A2UIRenderer data={data} />);
      // The root renders but no visible content
      expect(container.querySelector(".a2ui-root")).toBeInTheDocument();
    });
  });

  // ─── Root detection ─────────────────────────────────────────────────────

  describe("Root detection", () => {
    it("finds root components (not referenced as children)", () => {
      const data = makeMsgWithIds([
        { id: "root", component: "Column", children: ["child"] },
        { id: "child", component: "Text", text: "I am a child" },
      ]);
      render(<A2UIRenderer data={data} />);
      // Only the root Column should be rendered at top level
      expect(screen.getByText("I am a child")).toBeInTheDocument();
    });

    it("falls back to first component when all are children", () => {
      // Edge case: all components reference each other
      const data = makeMsgWithIds([
        { id: "a", component: "Text", text: "Fallback root" },
      ]);
      render(<A2UIRenderer data={data} />);
      expect(screen.getByText("Fallback root")).toBeInTheDocument();
    });
  });
});
