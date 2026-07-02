/**
 * Tests for groupIntoTurns() context-stripping behavior in chat-helpers.ts.
 *
 * The __SRE_VIEW_CTX__ markers are injected by ChatSlideOver/ChatInterface to
 * attach view context for the LLM.  groupIntoTurns() strips them so the raw
 * context block never appears in the user's chat bubble.
 */

import { groupIntoTurns } from "@/lib/chat-helpers";

// Helper to create a minimal user message object matching the shape
// groupIntoTurns expects (role + content + id).
function userMsg(content: string, id = "u1") {
  return { role: "user", content, id };
}

function assistantMsg(content: string, id = "a1") {
  return { role: "assistant", content, id };
}

describe("groupIntoTurns – __SRE_VIEW_CTX__ stripping", () => {
  it("strips __SRE_VIEW_CTX__ block from user messages", () => {
    const msg = userMsg(
      "__SRE_VIEW_CTX_START__\ncontext data\n__SRE_VIEW_CTX_END__\n\nactual question"
    );
    const turns = groupIntoTurns([msg]);

    expect(turns).toHaveLength(1);
    expect(turns[0].type).toBe("user");
    expect((turns[0] as { type: "user"; content: string }).content).toBe("actual question");
  });

  it("does NOT strip user-typed text with a different format", () => {
    const msg = userMsg("[CONTEXT] foo [/CONTEXT]");
    const turns = groupIntoTurns([msg]);

    expect(turns).toHaveLength(1);
    expect((turns[0] as { type: "user"; content: string }).content).toBe(
      "[CONTEXT] foo [/CONTEXT]"
    );
  });

  it("passes through plain text messages unchanged", () => {
    const msg = userMsg("What is the health of my app?");
    const turns = groupIntoTurns([msg]);

    expect(turns).toHaveLength(1);
    expect((turns[0] as { type: "user"; content: string }).content).toBe(
      "What is the health of my app?"
    );
  });

  it("handles empty context block", () => {
    const msg = userMsg(
      "__SRE_VIEW_CTX_START__\n\n__SRE_VIEW_CTX_END__\n\nquestion"
    );
    const turns = groupIntoTurns([msg]);

    expect(turns).toHaveLength(1);
    expect((turns[0] as { type: "user"; content: string }).content).toBe("question");
  });

  it("strips only the first context block when multiple are present", () => {
    // The regex uses the non-greedy [\s\S]*? quantifier, so it matches the
    // shortest span between START and END markers — i.e. each block individually.
    // Both blocks should therefore be stripped.
    const msg = userMsg(
      "__SRE_VIEW_CTX_START__\nblock1\n__SRE_VIEW_CTX_END__\n\n" +
      "__SRE_VIEW_CTX_START__\nblock2\n__SRE_VIEW_CTX_END__\n\nmy question"
    );
    const turns = groupIntoTurns([msg]);

    expect(turns).toHaveLength(1);
    // With the /g flag both blocks are stripped
    expect((turns[0] as { type: "user"; content: string }).content).toBe("my question");
  });

  it("does not affect assistant messages", () => {
    const msg = assistantMsg(
      "__SRE_VIEW_CTX_START__\nshould stay\n__SRE_VIEW_CTX_END__\n\nanswer"
    );
    const turns = groupIntoTurns([msg]);

    expect(turns).toHaveLength(1);
    expect(turns[0].type).toBe("assistant");
    // Assistant content is NOT stripped — the regex only runs on user turns
    const segments = (turns[0] as { type: "assistant"; segments: Array<{ kind: string; content?: string }> }).segments;
    expect(segments).toHaveLength(1);
    expect(segments[0].content).toContain("__SRE_VIEW_CTX_START__");
  });

  it("results in empty string when message is only a context block", () => {
    const msg = userMsg(
      "__SRE_VIEW_CTX_START__\ncontext only\n__SRE_VIEW_CTX_END__\n"
    );
    const turns = groupIntoTurns([msg]);

    expect(turns).toHaveLength(1);
    expect((turns[0] as { type: "user"; content: string }).content).toBe("");
  });
});
