import React from "react";
import { render, screen } from "@testing-library/react";
import { InlineMarkdown } from "@/components/tables/InlineMarkdown";

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("InlineMarkdown", () => {
  // ── Plain text ───────────────────────────────────────────────────────────────

  describe("plain text", () => {
    it("renders plain text as a span element", () => {
      const { container } = render(<InlineMarkdown text="Hello world" />);
      const span = container.querySelector("span");
      expect(span).toBeInTheDocument();
      expect(span).toHaveTextContent("Hello world");
    });

    it("renders text with no markdown as a single span", () => {
      const { container } = render(<InlineMarkdown text="no markdown here" />);
      const spans = container.querySelectorAll("span");
      expect(spans).toHaveLength(1);
      expect(spans[0]).toHaveTextContent("no markdown here");
    });

    it("renders an empty string without crashing", () => {
      const { container } = render(<InlineMarkdown text="" />);
      // An empty string produces a single empty span
      expect(container).toBeInTheDocument();
    });
  });

  // ── Bold ─────────────────────────────────────────────────────────────────────

  describe("bold (**text**)", () => {
    it("renders **bold** as a <strong> element", () => {
      render(<InlineMarkdown text="**bold**" />);
      const strong = screen.getByText("bold");
      expect(strong.tagName).toBe("STRONG");
    });

    it("strips the ** delimiters from the rendered text", () => {
      render(<InlineMarkdown text="**bold**" />);
      expect(screen.getByText("bold").textContent).toBe("bold");
    });

    it("renders bold text with the font-semibold class", () => {
      render(<InlineMarkdown text="**semibold**" />);
      expect(screen.getByText("semibold")).toHaveClass("font-semibold");
    });

    it("preserves surrounding plain text alongside bold", () => {
      const { container } = render(<InlineMarkdown text="Hello **world** again" />);
      // RTL normalizes whitespace so we match with exact:false or check the span directly
      const spans = container.querySelectorAll("span");
      const spanTexts = Array.from(spans).map((s) => s.textContent);
      expect(spanTexts).toContain("Hello ");
      expect(screen.getByText("world").tagName).toBe("STRONG");
      expect(spanTexts).toContain(" again");
    });

    it("renders bold with internal spaces", () => {
      render(<InlineMarkdown text="**multiple words**" />);
      expect(screen.getByText("multiple words").tagName).toBe("STRONG");
    });
  });

  // ── Italic ───────────────────────────────────────────────────────────────────

  describe("italic (*text*)", () => {
    it("renders *italic* as an <em> element", () => {
      render(<InlineMarkdown text="*italic*" />);
      const em = screen.getByText("italic");
      expect(em.tagName).toBe("EM");
    });

    it("strips the * delimiters from the rendered text", () => {
      render(<InlineMarkdown text="*italic*" />);
      expect(screen.getByText("italic").textContent).toBe("italic");
    });

    it("preserves surrounding plain text alongside italic", () => {
      const { container } = render(<InlineMarkdown text="before *italic* after" />);
      const spans = container.querySelectorAll("span");
      const spanTexts = Array.from(spans).map((s) => s.textContent);
      expect(spanTexts).toContain("before ");
      expect(screen.getByText("italic").tagName).toBe("EM");
      expect(spanTexts).toContain(" after");
    });
  });

  // ── Inline code ──────────────────────────────────────────────────────────────

  describe("inline code (`text`)", () => {
    it("renders `code` as a <code> element", () => {
      render(<InlineMarkdown text="`myFunc()`" />);
      const code = screen.getByText("myFunc()");
      expect(code.tagName).toBe("CODE");
    });

    it("strips the backtick delimiters from the rendered text", () => {
      render(<InlineMarkdown text="`snippet`" />);
      expect(screen.getByText("snippet").textContent).toBe("snippet");
    });

    it("applies styling classes to the code element", () => {
      render(<InlineMarkdown text="`styled`" />);
      const code = screen.getByText("styled");
      expect(code).toHaveClass("font-mono");
      expect(code).toHaveClass("text-pink-600");
    });

    it("preserves surrounding text alongside inline code", () => {
      const { container } = render(<InlineMarkdown text="Run `npm install` first" />);
      const spans = container.querySelectorAll("span");
      const spanTexts = Array.from(spans).map((s) => s.textContent);
      expect(spanTexts).toContain("Run ");
      expect(screen.getByText("npm install").tagName).toBe("CODE");
      expect(spanTexts).toContain(" first");
    });
  });

  // ── Markdown links ───────────────────────────────────────────────────────────

  describe("markdown links ([text](url))", () => {
    it("renders [link text](url) as an anchor element", () => {
      render(<InlineMarkdown text="[click here](https://example.com)" />);
      const link = screen.getByRole("link", { name: "click here" });
      expect(link).toBeInTheDocument();
    });

    it("sets the correct href on the anchor", () => {
      render(<InlineMarkdown text="[docs](https://docs.example.com)" />);
      expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute(
        "href",
        "https://docs.example.com"
      );
    });

    it("opens markdown links in a new tab (target=_blank)", () => {
      render(<InlineMarkdown text="[open](https://example.com)" />);
      expect(screen.getByRole("link", { name: "open" })).toHaveAttribute(
        "target",
        "_blank"
      );
    });

    it("sets rel=noopener noreferrer on markdown links", () => {
      render(<InlineMarkdown text="[safe](https://example.com)" />);
      expect(screen.getByRole("link", { name: "safe" })).toHaveAttribute(
        "rel",
        "noopener noreferrer"
      );
    });

    it("renders the link text (not the URL) as the anchor content", () => {
      render(<InlineMarkdown text="[my link text](https://example.com)" />);
      const link = screen.getByRole("link", { name: "my link text" });
      expect(link.textContent).toBe("my link text");
    });

    it("sets the title attribute to the URL for markdown links", () => {
      render(<InlineMarkdown text="[docs](https://example.com/docs)" />);
      expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute(
        "title",
        "https://example.com/docs"
      );
    });
  });

  // ── Bare URL links ───────────────────────────────────────────────────────────

  describe("bare URLs (https://...)", () => {
    it("renders a bare https URL as an anchor element", () => {
      render(<InlineMarkdown text="https://example.com" />);
      const link = screen.getByRole("link", { name: "https://example.com" });
      expect(link).toBeInTheDocument();
    });

    it("sets href equal to the bare URL itself", () => {
      render(<InlineMarkdown text="https://example.com/path" />);
      expect(
        screen.getByRole("link", { name: "https://example.com/path" })
      ).toHaveAttribute("href", "https://example.com/path");
    });

    it("opens bare URL links in a new tab (target=_blank)", () => {
      render(<InlineMarkdown text="https://example.com" />);
      expect(screen.getByRole("link")).toHaveAttribute("target", "_blank");
    });

    it("sets rel=noopener noreferrer on bare URL links", () => {
      render(<InlineMarkdown text="https://example.com" />);
      expect(screen.getByRole("link")).toHaveAttribute(
        "rel",
        "noopener noreferrer"
      );
    });

    it("renders an http:// URL as an anchor as well", () => {
      render(<InlineMarkdown text="http://example.com" />);
      expect(screen.getByRole("link")).toHaveAttribute(
        "href",
        "http://example.com"
      );
    });

    it("sets the title attribute to the bare URL", () => {
      render(<InlineMarkdown text="https://example.com/page" />);
      expect(screen.getByRole("link")).toHaveAttribute(
        "title",
        "https://example.com/page"
      );
    });
  });

  // ── Mixed content ────────────────────────────────────────────────────────────

  describe("mixed inline content", () => {
    it("renders bold and italic together in the same string", () => {
      render(<InlineMarkdown text="Hello **world** and *italic*" />);
      expect(screen.getByText("world").tagName).toBe("STRONG");
      expect(screen.getByText("italic").tagName).toBe("EM");
    });

    it("renders bold, code, and a link in the same string", () => {
      render(
        <InlineMarkdown text="**bold** and `code` and [link](https://example.com)" />
      );
      expect(screen.getByText("bold").tagName).toBe("STRONG");
      expect(screen.getByText("code").tagName).toBe("CODE");
      expect(screen.getByRole("link", { name: "link" })).toBeInTheDocument();
    });

    it("renders a mix of plain text, markdown link, and bare URL", () => {
      render(
        <InlineMarkdown text="Check [docs](https://docs.io) or https://alt.io" />
      );
      expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute(
        "href",
        "https://docs.io"
      );
      expect(screen.getByRole("link", { name: "https://alt.io" })).toHaveAttribute(
        "href",
        "https://alt.io"
      );
    });

    it("preserves plain text segments between multiple bold spans", () => {
      const { container } = render(<InlineMarkdown text="**one** middle **two**" />);
      expect(screen.getByText("one").tagName).toBe("STRONG");
      const spans = container.querySelectorAll("span");
      const spanTexts = Array.from(spans).map((s) => s.textContent);
      expect(spanTexts).toContain(" middle ");
      expect(screen.getByText("two").tagName).toBe("STRONG");
    });

    it("handles text with only plain characters without creating extra elements", () => {
      const { container } = render(
        <InlineMarkdown text="just plain text" />
      );
      // Should have no anchors, strongs, ems, or codes
      expect(container.querySelector("a")).not.toBeInTheDocument();
      expect(container.querySelector("strong")).not.toBeInTheDocument();
      expect(container.querySelector("em")).not.toBeInTheDocument();
      expect(container.querySelector("code")).not.toBeInTheDocument();
    });

    it("renders a trailing bare URL after normal text", () => {
      const { container } = render(<InlineMarkdown text="See https://example.com" />);
      const spans = container.querySelectorAll("span");
      const spanTexts = Array.from(spans).map((s) => s.textContent);
      expect(spanTexts).toContain("See ");
      expect(screen.getByRole("link")).toHaveAttribute(
        "href",
        "https://example.com"
      );
    });
  });

  // ── Edge cases ───────────────────────────────────────────────────────────────

  describe("edge cases", () => {
    it("does not confuse a single asterisk with bold or italic markers", () => {
      // A lone * not wrapping any text should just be rendered as-is (plain span)
      render(<InlineMarkdown text="price is 5 * 3" />);
      expect(screen.getByText("price is 5 * 3")).toBeInTheDocument();
      expect(document.querySelector("strong")).not.toBeInTheDocument();
      expect(document.querySelector("em")).not.toBeInTheDocument();
    });

    it("renders a URL with query params correctly", () => {
      render(
        <InlineMarkdown text="https://example.com/search?q=hello&page=2" />
      );
      expect(screen.getByRole("link")).toHaveAttribute(
        "href",
        "https://example.com/search?q=hello&page=2"
      );
    });

    it("renders a markdown link with a URL that contains a path", () => {
      render(
        <InlineMarkdown text="[API ref](https://api.example.com/v1/endpoint)" />
      );
      expect(
        screen.getByRole("link", { name: "API ref" })
      ).toHaveAttribute("href", "https://api.example.com/v1/endpoint");
    });
  });
});
