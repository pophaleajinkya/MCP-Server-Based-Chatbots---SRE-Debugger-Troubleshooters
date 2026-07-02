/**
 * Next.js Instrumentation Hook
 *
 * Runs once when the server initializes (before any requests are handled).
 * Loads environment variables in priority order:
 *   1. /secrets/.env.* files  → container deployments (stage / prod via Kitt/akeyless)
 *   2. ../.env.local           → parent-directory local file (local dev / build testing)
 *
 * Variables already set in process.env are never overwritten (override: false),
 * so real environment variables always win over file-based ones.
 */

/**
 * Parse a .env file content into key/value pairs.
 * Handles: blank lines, # comments, quoted values, inline comments.
 */
function parseEnvContent(content: string): Record<string, string> {
  const vars: Record<string, string> = {};

  for (const raw of content.split("\n")) {
    const line = raw.trim();

    // Skip blank lines and comments
    if (!line || line.startsWith("#")) continue;

    const eqIdx = line.indexOf("=");
    if (eqIdx === -1) continue;

    const key = line.slice(0, eqIdx).trim();
    if (!key) continue;

    let value = line.slice(eqIdx + 1).trim();

    // Strip surrounding single or double quotes
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    // Strip inline comments (e.g.  VALUE=foo  # comment)
    const commentIdx = value.indexOf(" #");
    if (commentIdx !== -1) {
      value = value.slice(0, commentIdx).trim();
    }

    vars[key] = value;
  }

  return vars;
}

/**
 * Load a single env file into process.env (non-overriding).
 * Returns the number of variables loaded.
 */
function loadEnvFile(filePath: string, fs: typeof import("fs")): number {
  try {
    const content = fs.readFileSync(filePath, "utf-8");
    const parsed = parseEnvContent(content);
    let count = 0;

    for (const [key, value] of Object.entries(parsed)) {
      if (!(key in process.env)) {
        process.env[key] = value;
        count++;
      }
    }

    if (count > 0) {
      console.info(`[env] Loaded ${count} variable(s) from ${filePath}`);
    }

    return count;
  } catch {
    // File unreadable — silently skip
    return 0;
  }
}

export async function register() {
  // Only run in the Node.js runtime (not in Edge runtime)
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  const fs = await import(/* webpackIgnore: true */ "fs");
  const path = await import(/* webpackIgnore: true */ "path");

  // ── 1. /secrets/.env.* ── container deployments (stage / prod) ──────────
  const secretsDir = "/secrets";

  if (fs.existsSync(secretsDir)) {
    let secretFiles: string[] = [];

    try {
      secretFiles = fs
        .readdirSync(secretsDir)
        .filter((f) => f.startsWith(".env"))
        .sort(); // deterministic order
    } catch {
      // Cannot read directory — skip
    }

    for (const file of secretFiles) {
      loadEnvFile(path.join(secretsDir, file), fs);
    }
  }

  // ── 2. ../.env.local ── parent directory (local dev / build testing) ────
  const parentEnvLocal = path.resolve(process.cwd(), "..", ".env.local");

  if (fs.existsSync(parentEnvLocal)) {
    loadEnvFile(parentEnvLocal, fs);
  }
}
