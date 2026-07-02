import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

// Activate the manual mock at <rootDir>/__mocks__/mermaid.ts.
// Because mermaid is an ESM-only node_modules package, jest.mock() with a
// factory cannot reliably intercept `await import("mermaid")`.  The manual
// mock file is resolved by Jest's module registry for both static and dynamic
// imports under ts-jest.
jest.mock("mermaid");

// Import the mocked default so tests can reconfigure it.
import mermaid from "mermaid";

import MermaidDiagram from "@/components/MermaidDiagram";

// ─── Helpers ──────────────────────────────────────────────────────────────────

const VALID_DIAGRAM = "graph TD\nA-->B";

// ─── Tests ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();
  // Restore the default happy-path resolution before each test.
  (mermaid.parse as jest.Mock).mockResolvedValue(true);
  (mermaid.render as jest.Mock).mockResolvedValue({ svg: "<svg>test diagram</svg>" });
  (mermaid.initialize as jest.Mock).mockReset();
});

describe("MermaidDiagram", () => {
  describe("null / empty diagram", () => {
    it("returns null when diagram prop is undefined", () => {
      const { container } = render(<MermaidDiagram />);
      expect(container.firstChild).toBeNull();
    });

    it("returns null when diagram prop is null", () => {
      const { container } = render(<MermaidDiagram diagram={null} />);
      expect(container.firstChild).toBeNull();
    });

    it("returns null when diagram prop is an empty string", () => {
      const { container } = render(<MermaidDiagram diagram="" />);
      expect(container.firstChild).toBeNull();
    });

    it("does not call mermaid.initialize when diagram is null", async () => {
      render(<MermaidDiagram diagram={null} />);
      await act(async () => {});
      expect(mermaid.initialize).not.toHaveBeenCalled();
    });

    it("does not call mermaid.render when diagram is null", async () => {
      render(<MermaidDiagram diagram={null} />);
      await act(async () => {});
      expect(mermaid.render).not.toHaveBeenCalled();
    });
  });

  describe("successful render", () => {
    it("renders the SVG content returned by mermaid.render", async () => {
      const { container } = render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(container.innerHTML).toContain("test diagram");
      });
    });

    it("sets SVG content via dangerouslySetInnerHTML", async () => {
      const { container } = render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        // The rendered SVG markup is injected via dangerouslySetInnerHTML.
        expect(container.innerHTML).toContain("<svg>test diagram</svg>");
      });
    });

    it("calls mermaid.initialize with the config object", async () => {
      render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(mermaid.initialize).toHaveBeenCalledTimes(1);
        expect(mermaid.initialize).toHaveBeenCalledWith(
          expect.objectContaining({
            startOnLoad: false,
            theme: "default",
            securityLevel: "loose",
          })
        );
      });
    });

    it("calls mermaid.render with a generated id and the diagram string", async () => {
      render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(mermaid.render).toHaveBeenCalledTimes(1);
        const [id, diagramArg] = (mermaid.render as jest.Mock).mock.calls[0];
        expect(id).toMatch(/^mermaid-\d+$/);
        expect(diagramArg).toBe(VALID_DIAGRAM);
      });
    });

    it("does not show an error message on successful render", async () => {
      render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(mermaid.render).toHaveBeenCalledTimes(1);
      });

      expect(screen.queryByText("Failed to load diagram")).not.toBeInTheDocument();
    });

    it("does not show a Retry button on successful render", async () => {
      render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(mermaid.render).toHaveBeenCalledTimes(1);
      });

      expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    });
  });

  describe("error state", () => {
    it("shows 'Failed to load diagram' when mermaid.render rejects", async () => {
      (mermaid.render as jest.Mock).mockRejectedValue(new Error("parse error"));

      render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(screen.getByText("Failed to load diagram")).toBeInTheDocument();
      });
    });

    it("shows Retry button when there is an error", async () => {
      (mermaid.render as jest.Mock).mockRejectedValue(new Error("parse error"));

      render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
      });
    });

    it("does not render SVG content when in error state", async () => {
      (mermaid.render as jest.Mock).mockRejectedValue(new Error("fail"));

      const { container } = render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(screen.getByText("Failed to load diagram")).toBeInTheDocument();
        expect(container.innerHTML).not.toContain("test diagram");
      });
    });

    it("shows error when mermaid.initialize throws", async () => {
      (mermaid.initialize as jest.Mock).mockImplementationOnce(() => {
        throw new Error("init failed");
      });

      render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(screen.getByText("Failed to load diagram")).toBeInTheDocument();
      });
    });
  });

  describe("Retry button", () => {
    it("clicking Retry re-calls mermaid.render (retryCount increments)", async () => {
      (mermaid.render as jest.Mock).mockRejectedValueOnce(new Error("first attempt fails"));

      render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
      });

      // On second call, succeed.
      (mermaid.render as jest.Mock).mockResolvedValueOnce({ svg: "<svg>retry succeeded</svg>" });

      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /retry/i }));
      });

      await waitFor(() => {
        expect(mermaid.render).toHaveBeenCalledTimes(2);
      });
    });

    it("clicking Retry clears the error and renders SVG on success", async () => {
      (mermaid.render as jest.Mock).mockRejectedValueOnce(new Error("temporary failure"));

      render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(screen.getByText("Failed to load diagram")).toBeInTheDocument();
      });

      (mermaid.render as jest.Mock).mockResolvedValueOnce({ svg: "<svg>recovered</svg>" });

      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /retry/i }));
      });

      await waitFor(() => {
        expect(screen.queryByText("Failed to load diagram")).not.toBeInTheDocument();
      });
    });

    it("clicking Retry multiple times keeps calling mermaid.render", async () => {
      (mermaid.render as jest.Mock).mockRejectedValue(new Error("persistent error"));

      render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /retry/i }));
      });
      await waitFor(() => expect(mermaid.render).toHaveBeenCalledTimes(2));

      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /retry/i }));
      });
      await waitFor(() => expect(mermaid.render).toHaveBeenCalledTimes(3));
    });
  });

  describe("center prop — CSS classes", () => {
    it("applies 'w-fit max-w-full' class when center=true", async () => {
      const { container } = render(
        <MermaidDiagram diagram={VALID_DIAGRAM} center={true} />
      );

      await waitFor(() => {
        expect(container.innerHTML).toContain("test diagram");
      });

      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper).toHaveClass("w-fit");
      expect(wrapper).toHaveClass("max-w-full");
    });

    it("does NOT apply 'w-fit' class when center=false", async () => {
      const { container } = render(
        <MermaidDiagram diagram={VALID_DIAGRAM} center={false} />
      );

      await waitFor(() => {
        expect(container.innerHTML).toContain("test diagram");
      });

      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper).not.toHaveClass("w-fit");
    });

    it("applies 'w-full' class when center=false", async () => {
      const { container } = render(
        <MermaidDiagram diagram={VALID_DIAGRAM} center={false} />
      );

      await waitFor(() => {
        expect(container.innerHTML).toContain("test diagram");
      });

      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper).toHaveClass("w-full");
    });

    it("applies 'w-full' class when center prop is omitted", async () => {
      const { container } = render(<MermaidDiagram diagram={VALID_DIAGRAM} />);

      await waitFor(() => {
        expect(container.innerHTML).toContain("test diagram");
      });

      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper).toHaveClass("w-full");
    });

    it("does NOT apply 'w-full' class when center=true", async () => {
      const { container } = render(
        <MermaidDiagram diagram={VALID_DIAGRAM} center={true} />
      );

      await waitFor(() => {
        expect(container.innerHTML).toContain("test diagram");
      });

      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper).not.toHaveClass("w-full");
    });
  });

  describe("diagram prop changes", () => {
    it("re-renders when diagram prop changes", async () => {
      const DIAGRAM_B = "graph LR\nC-->D";
      (mermaid.render as jest.Mock)
        .mockResolvedValueOnce({ svg: "<svg>first diagram</svg>" })
        .mockResolvedValueOnce({ svg: "<svg>second diagram</svg>" });

      const { rerender, container } = render(
        <MermaidDiagram diagram={VALID_DIAGRAM} />
      );

      await waitFor(() => {
        expect(container.innerHTML).toContain("first diagram");
      });

      rerender(<MermaidDiagram diagram={DIAGRAM_B} />);

      await waitFor(() => {
        expect(container.innerHTML).toContain("second diagram");
      });

      expect(mermaid.render).toHaveBeenCalledTimes(2);
    });

    it("renders null when diagram changes to null after a successful render", async () => {
      const { rerender, container } = render(
        <MermaidDiagram diagram={VALID_DIAGRAM} />
      );

      await waitFor(() => {
        expect(container.innerHTML).toContain("test diagram");
      });

      rerender(<MermaidDiagram diagram={null} />);

      // The component short-circuits to null when diagram is falsy.
      expect(container.firstChild).toBeNull();
    });

    it("renders null when diagram changes to empty string after a successful render", async () => {
      const { rerender, container } = render(
        <MermaidDiagram diagram={VALID_DIAGRAM} />
      );

      await waitFor(() => {
        expect(container.innerHTML).toContain("test diagram");
      });

      rerender(<MermaidDiagram diagram="" />);

      expect(container.firstChild).toBeNull();
    });
  });
});
