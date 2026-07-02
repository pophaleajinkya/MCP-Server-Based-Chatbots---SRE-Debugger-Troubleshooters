"""A2UI (Agent-to-UI) integration for structured UI responses.

Provides the A2UI schema manager, instruction generation, and response
validation so the agent can emit rich UI components (cards, tables, charts)
as structured JSON alongside conversational text.

The A2UI instruction is appended to the agent's base instruction when
A2UI_ENABLED=true.  A ``validate_a2ui_response`` helper is exposed for
downstream consumers (SSE router, A2A handler) to parse and validate
LLM output before sending it to the client.

See: https://a2ui.org  |  https://google.github.io/adk-docs/integrations/a2ui/
"""

import json
import logging
from pathlib import Path

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.core.parser.parser import has_a2ui_parts, parse_response
from a2ui.core.parser.response_part import ResponsePart
from a2ui.core.schema.constants import VERSION_0_9
from a2ui.core.schema.manager import A2uiSchemaManager

log = logging.getLogger(__name__)

# ── Allowed components ────────────────────────────────────────────────────────
# Restrict the catalog to components the SRE UI renderer supports.
# Empty list = all components from the basic catalog are allowed.
_ALLOWED_COMPONENTS: list[str] = [
    "Text",       # variant: h1-h5, body, caption  (v0.9 — NOT "Heading")
    "Card",       # child: single component ID
    "Button",     # child + action  (NOT label/url)
    "Table",      # columns: string[], rows: string[][]
    "Chart",      # chartType, xAxis.labels, series
    "Image",
    "Divider",
    "Column",
    "Row",
    "Tabs",       # tabItems: [{title, child}]
    "Icon",       # name: check | warning | error | info
]

# ── Schema manager (singleton) ───────────────────────────────────────────────

_schema_manager: A2uiSchemaManager | None = None


def _get_schema_manager() -> A2uiSchemaManager:
    """Lazily initialise and return the A2UI schema manager singleton."""
    global _schema_manager
    if _schema_manager is None:
        _schema_manager = A2uiSchemaManager(
            version=VERSION_0_9,
            catalogs=[BasicCatalog.get_config(version=VERSION_0_9)],
        )
        log.info(
            "A2UI schema manager initialised — version=%s, catalogs=%s",
            VERSION_0_9,
            _schema_manager.supported_catalog_ids,
        )
    return _schema_manager


# ── Instruction generation ───────────────────────────────────────────────────

_A2UI_PATTERNS_FILE = Path(__file__).parents[2] / "resources" / "A2UI_PATTERNS.md"


def generate_a2ui_instruction() -> str:
    """Load A2UI v0.9 pattern guide from resources/A2UI_PATTERNS.md.

    The patterns file contains format rules + 6 concrete examples (table,
    card, chart, tabs, bar chart, mixed layout). MCPs return pure JSON;
    this instruction teaches the LLM how to render any structured data.

    Edit A2UI_PATTERNS.md to add new patterns — no code change needed.
    Restart the agent for changes to take effect (file is read at startup).
    """
    try:
        text = _A2UI_PATTERNS_FILE.read_text(encoding="utf-8").strip()
        log.info("A2UI patterns loaded from %s (%d chars)", _A2UI_PATTERNS_FILE.name, len(text))
        return text
    except FileNotFoundError:
        log.warning("A2UI_PATTERNS.md not found at %s — A2UI instruction skipped", _A2UI_PATTERNS_FILE)
        return ""


# ── Response validation ──────────────────────────────────────────────────────


def validate_a2ui_response(
    llm_output: str,
) -> list[ResponsePart]:
    """Parse and validate A2UI blocks in the LLM output.

    Args:
        llm_output: Raw text output from the LLM that may contain A2UI blocks
                    wrapped in ``<a2ui>`` / ``</a2ui>`` tags.

    Returns:
        List of ``ResponsePart`` objects.  Each part has:
          - ``.text``      — conversational text (may be empty)
          - ``.a2ui_json`` — parsed + validated A2UI JSON (None if text-only)

    Raises:
        ValueError: If the A2UI tags are present but the JSON is malformed or
                    fails schema validation.
    """
    if not has_a2ui_parts(llm_output):
        return [ResponsePart(text=llm_output)]

    mgr = _get_schema_manager()
    catalog = mgr.get_selected_catalog(allowed_components=_ALLOWED_COMPONENTS)
    validator = catalog.validator

    parts = parse_response(llm_output)

    for part in parts:
        if part.a2ui_json is not None:
            validator.validate(part.a2ui_json)
            log.debug(
                "A2UI block validated OK (%d bytes)",
                len(json.dumps(part.a2ui_json)),
            )

    return parts


def try_validate_a2ui_response(
    llm_output: str,
) -> tuple[list[ResponsePart], str | None]:
    """Parse and validate A2UI, returning errors as a string instead of raising.

    Convenience wrapper around ``validate_a2ui_response`` for call sites that
    want graceful degradation (fall back to plain text on invalid A2UI).

    Returns:
        (parts, error) — ``error`` is None on success, or a human-readable
        validation error string on failure.
    """
    try:
        parts = validate_a2ui_response(llm_output)
        return parts, None
    except Exception as exc:
        log.warning("A2UI validation failed — falling back to plain text: %s", exc)
        return [ResponsePart(text=llm_output)], str(exc)


