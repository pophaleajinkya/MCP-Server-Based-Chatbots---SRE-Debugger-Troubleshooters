/**
 * Auto-fix common mermaid syntax issues that break v11 rendering.
 * Sanitizes content BEFORE passing to mermaid.render().
 *
 * Used by both MermaidBlock (chat) and MermaidDiagram (side-panel).
 */
export function autoFixMermaid(raw: string): string {
  let fixed = raw.trim();

  // 1. Ensure diagram starts with a valid directive
  if (
    !/^(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|gitgraph|mindmap|timeline|quadrantChart|sankey|xychart)/m.test(
      fixed
    )
  ) {
    if (/\w+\s*-->/.test(fixed) || /\w+\s*--\s/.test(fixed)) {
      fixed = "graph LR\n" + fixed;
    }
  }

  // 2. Fix node IDs with hyphens (bare IDs only, not inside quoted labels)
  fixed = fixed.replace(
    /^(\s*)([a-zA-Z][\w-]*-[\w-]+)((?:\s*-->|\s*---|\s*-.->|\s*==>|\s*\|))/gm,
    (_match, indent: string, id: string, arrow: string) =>
      `${indent}${id.replace(/-/g, "_")}${arrow}`
  );
  fixed = fixed.replace(
    /(-->|---|-.->|==>)\s*([a-zA-Z][\w-]*-[\w-]+)(\s*$|\s*\[)/gm,
    (_match, arrow: string, id: string, suffix: string) =>
      `${arrow} ${id.replace(/-/g, "_")}${suffix}`
  );

  // 3. Escape unquoted labels with special characters
  fixed = fixed.replace(/\[([^\]"]+)\]/g, (_match, label: string) => {
    if (/[(){};<>#&|]/.test(label)) {
      const safe = label
        .replace(/"/g, "'")
        .replace(/\(/g, "❨")
        .replace(/\)/g, "❩")
        .replace(/</g, "‹")
        .replace(/>/g, "›")
        .replace(/#/g, "＃")
        .replace(/&/g, "+")
        .replace(/;/g, ",")
        .replace(/\|/g, "/");
      return `["${safe}"]`;
    }
    return `["${label}"]`;
  });

  // 4. Remove trailing semicolons, fix doubled arrows, collapse blank lines
  fixed = fixed.replace(/;\s*$/gm, "");
  fixed = fixed.replace(/--> -->/g, "-->");
  fixed = fixed.replace(/\n{3,}/g, "\n\n");

  return fixed;
}

/** Escape characters that break mermaid v11 inside double-quoted labels. */
export function safeMermaidLabel(value: string | undefined | null): string {
  return (value || "Unknown")
    .replace(/"/g, "'")
    .replace(/\(/g, "❨")
    .replace(/\)/g, "❩")
    .replace(/\[/g, "⟦")
    .replace(/\]/g, "⟧")
    .replace(/\{/g, "⟨")
    .replace(/\}/g, "⟩")
    .replace(/</g, "‹")
    .replace(/>/g, "›")
    .replace(/#/g, "＃")
    .replace(/&/g, "+")
    .replace(/;/g, ",")
    .replace(/\|/g, "/");
}

/** Node IDs must be alphanumeric + underscore only for mermaid v11. */
export function safeMermaidId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_]/g, "_");
}
