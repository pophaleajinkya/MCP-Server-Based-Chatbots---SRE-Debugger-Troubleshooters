# o2_mcp — OpenObserve MCP Server

An MCP (Model Context Protocol) server that gives any AI agent the ability to query
**OpenObserve** log streams using natural-language-to-SQL translation.

Built for Walmart's WCNP (Walmart Cloud Native Platform) Kubernetes workloads.
Works with Claude, Google ADK, Cursor, and any MCP-compatible agent.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Why 70% Prompt / 30% Tool?](#why-70-prompt--30-tool)
3. [Project Structure](#project-structure)
4. [MCP Primitives: Tools, Resources, Prompts](#mcp-primitives-tools-resources-prompts)
5. [Apache DataFusion — The SQL Engine](#apache-datafusion--the-sql-engine)
6. [SQLGlot — The SQL Parser](#sqlglot--the-sql-parser)
7. [Agent Workflow](#agent-workflow)
8. [Configuration](#configuration)
9. [Running the Server](#running-the-server)
10. [Development](#development)

---

## Quick Start

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env — set O2_ENDPOINT and O2_AUTH_TOKEN if using static credentials

# Run via stdio (standard MCP transport)
python -m src.server

# Run via HTTP (stateless, for chatbot/multi-agent setups)
FASTMCP_STATELESS_HTTP=1 fastmcp run src/server.py --transport streamable-http
```

Connect your MCP client to the server and start asking questions:

> *"Show me 5XX errors for my-app in namespace my-ns over the last hour"*

---

## Why 70% Prompt / 30% Tool?

Most developers instinct when building an AI integration is to create many tools —
one tool per operation. **This is the wrong approach.** Every tool call costs:

- A network round-trip (300 ms – 5 s)
- Token budget (schema + result + reasoning)
- An LLM reasoning step

The better design: **teach the agent everything it needs via resources and rich
descriptions, so it makes fewer but smarter tool calls.**

### The Core Insight

> LLMs are the compute. Tools are the I/O.

When an agent reads `o2://agent-guide` at session start, it loads 1,390 lines of
operational knowledge into its context window:

- Every SQL rule for OpenObserve's DataFusion dialect
- Every field naming convention in Walmart's k8s log streams
- Every error recovery pattern
- The exact retry loop algorithm

That single resource **replaces dozens of tools** that would otherwise have to
answer questions like "what's the right way to count rows?", "can I use SELECT \*?",
"how do I search full-text fields?". The agent already knows — no round-trip needed.

**Result:** The agent makes 3–5 focused tool calls instead of 15–20 exploratory ones.

### Without MCP vs. With MCP

```
WITHOUT MCP                          WITH MCP (o2_mcp)
─────────────────────────────────    ─────────────────────────────────────────
1. Parse intent (guesswork)          1. Reads o2://agent-guide → full workflow
2. Guess API endpoint                2. Calls health_mcp → real endpoint + stream
3. Guess stream name                 3. Gets fresh PingFed token from super-agent
4. Guess field names                 4. Calls get_stream_schema → exact fields
5. Generate SQL (wrong dialect)      5. Generates correct ADL SQL from resources
6. Handle auth somehow               6. Calls validate_sql_policy → 5 ms check
7. No retry logic                    7. Calls execute_sql → real results
8. No schema awareness               8. Auth expired? Refresh token, retry (from guide)
```

The MCP server does not make the agent smarter.
**It makes the agent informed** — grounded in current, domain-specific knowledge
it could not have from training data alone.

---

## Project Structure

```
o2_mcp/
├── src/
│   ├── server.py                   ← thin orchestrator: creates mcp + registers providers
│   ├── config.py                   ← pydantic-settings (O2_ENDPOINT, O2_AUTH_TOKEN, etc.)
│   ├── http_client.py              ← O2HttpClient (httpx async), PingFed token conversion
│   │
│   ├── providers/                  ← FastMCP LocalProvider modules (MCP layer only)
│   │   ├── _shared.py              ← build_service(), read_doc(), path constants
│   │   ├── resources.py            ← 5 @provider.resource  (o2:// URIs)
│   │   ├── query.py                ← 5 network tools
│   │   ├── validation.py           ← 3 validation tools
│   │   ├── sql_tools.py            ← 5 local analysis tools
│   │   └── utils.py                ← 1 utility tool (get_time)
│   │
│   ├── services/
│   │   └── query_service.py        ← QueryService: all O2 API calls
│   │
│   ├── sql/                        ← SQL parsing & analysis (sqlglot-based, no MCP)
│   │   ├── models.py               ← SqlParseResult, SqlFacts, SqlAnalysisResult
│   │   ├── ast_parser.py           ← parse_sql() — no-throw, best-effort AST
│   │   └── analysis.py             ← analyze_sql() — extracts facts from AST
│   │
│   ├── tools/                      ← pure business logic, no FastMCP imports
│   │   ├── rules.py                ← RulesEngine (loads rules.json)
│   │   ├── sql_error_classifier.py ← classify SQL errors into structured types
│   │   ├── sql_function_registry.py← validate/lookup DataFusion functions
│   │   └── sql_policy.py           ← ADL policy checks (AST + regex)
│   │
│   └── utils/
│       └── logging.py
│
├── data/
│   ├── resources/                  ← static .md docs served as o2:// MCP resources
│   │   ├── AGENT.md                  (o2://agent-guide)
│   │   ├── datafusion_sql.md         (o2://datafusion-sql)  — 3,250 lines, 223 functions
│   │   ├── openobserve_functions.md  (o2://o2-functions)
│   │   └── openobserve.md            (o2://o2-guide)
│   ├── prompts/                    ← prompt templates with {placeholder} substitution
│   │   └── retry_guide.md            (o2://retry-guide, uses {max_retries})
│   ├── rules.json                  ← SQL/VRL rules for get_o2_rules
│   └── sql_functions.json          ← 236-function registry for validate_sql_functions
│
└── tests/
    └── ...                         ← 233 tests, all passing
```

**Key separation of concerns:**

| Layer | What it does | FastMCP imports? |
|-------|-------------|-----------------|
| `providers/` | MCP decorators + thin dispatch | Yes |
| `tools/` | Business logic, pure functions | No |
| `services/` | Network I/O | No |
| `sql/` | SQL parsing, no side effects | No |

The `tools/` and `sql/` modules are independently testable without running an MCP server.

---

## MCP Primitives: Tools, Resources, Prompts

MCP defines three building blocks. Understanding when to use each is the difference
between a mediocre and a powerful MCP server.

### Resources — The Agent's Textbook

```
o2://agent-guide        1,390 lines  Full workflow, SQL rules, field conventions
o2://datafusion-sql     3,250 lines  223 DataFusion functions with syntax + examples
o2://o2-functions         ~300 lines  20+ OpenObserve-specific UDFs
o2://o2-guide             ~400 lines  Dialect rules, observability patterns, VRL
o2://retry-guide          ~100 lines  Self-correction retry loop (dynamic: uses max_retries)
```

**Read once per session. Zero network calls. Zero latency.**

Resources are served from `data/resources/` and cached in-process on first read.
The agent loads them at session start and carries that knowledge through every
subsequent tool call.

### Tools — Live Instruments

Called only when the agent needs **current data** or needs to **execute a side effect**.

#### Network Tools — call the OpenObserve REST API

| MCP Tool | O2 REST Endpoint | Method | What it does |
|----------|-----------------|--------|--------------|
| `execute_sql` | `POST /{org}/_search?type=logs&use_cache=false` | POST | Executes a DataFusion SQL SELECT query. Body: `{"query": {"sql": "...", "start_time": <us>, "end_time": <us>, "size": N}}` |
| `search_around` | `GET /{org}/{stream}/_around?key=<timestamp_us>&size=N` | GET | Index-seek: returns N rows immediately before + after an exact microsecond timestamp. **Not SQL** — uses O2's internal index seek. |
| `get_field_values` | `POST /{org}/_search?type=logs&use_cache=false` | POST | Runs `SELECT field, COUNT(*) GROUP BY field ORDER BY count DESC` per field, all in parallel via `asyncio.gather`. Reuses the same `_search` endpoint as `execute_sql`. |
| `get_stream_schema` | `GET /{org}/streams/{stream}/schema?type=logs` | GET | Fetches raw stream schema (fields + settings). Response is pruned to token-efficient format before returning to agent. |
| `list_streams` | `GET /{org}/streams?fetchSchema=false&type=logs` | GET | Lists all streams in the org with optional schema inclusion. |
| `validate_sql` | `POST /{org}/_search?type=logs&use_cache=false` | POST | Same as `execute_sql` but with `quick_mode=true`, `size=1`, and a 1-second time window — cheap syntax/field validation with zero data scanned. |
| `validate_vrl` | `POST /{org}/_vrl` | POST | Sends VRL script + sample events to O2's VRL validation endpoint. Body: `{"vrl": "...", "events": [...]}` |

#### Local Tools — no network, no auth required

| MCP Tool | Latency | What it does |
|----------|---------|--------------|
| `validate_sql_policy` | ~2 ms | Parses SQL with sqlglot → walks AST → checks ADL rules (no `_timestamp` in WHERE, no `SELECT *`, no subquery in SELECT). Zero network. |
| `validate_sql_functions` | ~3 ms | Extracts all function names from SQL AST → checks each against the 236-function registry in `data/sql_functions.json`. Zero network. |
| `get_sql_correction_hint` | <1 ms | Classifies an error string into a structured type (`unknown_column`, `auth_error`, etc.) with fix strategy and suggested next tools. |
| `get_o2_rules` | <1 ms | Loads SQL/VRL rules from `data/rules.json`, returns formatted string for LLM prompt injection. |
| `search_docs` | ~5 ms | Regex search across `data/resources/*.md` doc files. Returns matching sections with surrounding context. |
| `get_time` | <1 ms | Returns current UTC microseconds + helpers for converting dates/time-ranges to O2 microsecond timestamps. |

**7 network tools. 6 local tools.** The local tools are the fast-path safety net
(< 10 ms total) that runs before any expensive network call.

### Prompts — Configurable Operating Procedures

`o2://retry-guide` is a **prompt template**, not a static resource. It's rendered
at request time with the current `max_retries` value from config:

```md
while attempt <= {max_retries}:        ← filled with cfg.max_retries at runtime
    result = execute_sql(...)
    ...
```

Change `O2_MAX_RETRIES=7` in your `.env` and the retry protocol updates
automatically — no code change, no restart required.

---

## Apache DataFusion — The SQL Engine

OpenObserve uses **Apache DataFusion** as its SQL query engine — a fast,
in-process columnar engine written in Rust, part of the Apache Arrow ecosystem.
The same engine powers InfluxDB 3.0 and several cloud-native observability platforms.

```
User SQL
  → DataFusion SQL Parser
    → Logical Plan (Apache Arrow schema)
      → Physical Plan
        → Vectorised execution over Parquet/JSON files
          → Results
```

### DataFusion Is Not PostgreSQL

Most LLMs were trained predominantly on PostgreSQL and MySQL syntax. DataFusion
has its own function set and dialect rules. Wrong functions mean failed queries.

| Operation | PostgreSQL (wrong for O2) | DataFusion / O2 (correct) |
|-----------|--------------------------|--------------------------|
| Row count | `COUNT(*)` | `COUNT(_timestamp)` |
| String search | `ILIKE '%error%'` | `str_match_ignore_case(field, 'error')` |
| Full-text search | `to_tsvector @@ to_tsquery` | `match_all('error')` |
| JSON extract | `json_extract_path_text(col, 'key')` | `spath(col, 'key')` |
| String format | `strftime('%Y', ts)` | ✗ does not exist |
| Percentile | `PERCENTILE_CONT(0.99) WITHIN GROUP` | `approx_percentile_cont(col, 0.99)` |
| Time histogram | `WIDTH_BUCKET()` | `histogram(_timestamp, 'minute')` |
| Array from field | `string_to_array(field, ',')` | `cast_to_arr(field)` |

### OpenObserve Extensions (ADL)

OpenObserve adds its own UDFs on top of DataFusion:

```sql
-- Full-text search over indexed fields (fastest path)
WHERE match_all('OOMKilled')

-- Fuzzy match — tolerates typos (distance=2)
WHERE fuzzy_match(message, 'connectoin', 2)

-- JSON path extraction from _raw field
SELECT spath(_raw, 'kubernetes.pod.name') AS pod_name

-- Time histogram — groups events into buckets
SELECT histogram(_timestamp, 'minute') AS ts, count(_timestamp) AS events
FROM "k8s_json"
GROUP BY ts ORDER BY ts

-- Array operations
SELECT cast_to_arr(tags) AS tag_array, arr_descending(scores) AS top_scores
```

These functions only exist in OpenObserve — not in standard DataFusion.
The `o2://o2-functions` resource documents all of them.

### Why the Reference Docs Are in Resources (Not Code)

The `data/resources/datafusion_sql.md` file is 3,250 lines covering all 223
DataFusion functions. This knowledge:
- Changes with DataFusion versions
- Is too large to embed in every tool description
- Is needed by the agent, not by the server code

Serving it as a resource means the agent can consult it on demand (`search_docs` tool
or full read via `o2://datafusion-sql`) without any server-side logic changes.

---

## SQLGlot — The SQL Parser

o2_mcp uses **[SQLGlot](https://github.com/tobymao/sqlglot)** — a pure-Python SQL
parser, AST builder, and transpiler — for static SQL analysis before any query
touches the network.

### What We Use It For

```
SQL string
  → sqlglot.parse() → AST
      → Policy checker (validate_sql_policy)        ~2 ms
          ✓ No _timestamp in WHERE clause?
          ✓ No SELECT *?
          ✓ No subquery in SELECT position?
      → Function scanner (validate_sql_functions)   ~3 ms
          ✓ Every function name in 236-fn registry?
      → SQL analysis (analyze_sql)
          → Selected columns, GROUP BY fields,
             aggregation vs. row query classification
```

**All of this runs locally in < 10 ms, zero network, zero auth required.**

### Why Not Regex?

Regex breaks on aliases, CTEs, and nested queries. Consider detecting `SELECT *`:

```sql
SELECT t.* FROM "stream" t              -- table-qualified star → regex misses
SELECT *, count(_timestamp) FROM ...    -- mixed star → regex misses
WITH cte AS (SELECT * FROM ...) ...     -- star in CTE → regex misses
```

SQLGlot's AST catches all of these because it understands SQL *structure*.
Walking the AST for a `Star` node in any projection position is exact and robust.

### The Dialect Chain

DataFusion is ANSI SQL with Postgres-flavoured extensions. SQLGlot has no native
DataFusion dialect, so we try two in sequence:

```python
_DIALECT_CHAIN = ("", "postgres")
# "" = generic ANSI  →  catches most standard SQL
# "postgres"         →  catches :: casts, ILIKE, etc.
```

Validated against 127 real OpenObserve SQL queries: 100% parse rate.

### WARN-mode Partial AST

Even when strict parsing fails, SQLGlot can return a **partial AST** via
`ErrorLevel.WARN`. o2_mcp uses this so the policy checker can still identify
violations in malformed SQL — giving the retry loop a structured diagnosis even
from broken queries.

### Why SQLGlot Over Alternatives

| Parser | Why not |
|--------|---------|
| **ClickHouse parser** | ClickHouse dialect only; no AST walk API in Python |
| **ANTLR grammar** | Requires compiled artifacts; too heavy for a pure-Python service |
| **sqlparse** | Tokeniser only — no AST, can't walk tree structure |
| **mo_sql_parsing** | Less maintained, fewer dialect options |
| **Custom regex** | Brittle on aliases, CTEs, subqueries |
| **SQLGlot** ✓ | Pure Python, 20+ dialects, real AST, production-tested at scale |

SQLGlot is also used by DuckDB's Python client and several cloud SQL platforms.

---

## Agent Workflow

```
User: "Show me 5XX errors for payment-service in prod over the last hour"

Step 1 — Resolve cluster config
  health_mcp.wcnp_get_o2_config(namespace="prod", app="payment-service")
  → endpoint, stream, organization, cluster_lb, default_filter

Step 2 — Obtain bearer token
  super-agent.pingfed_playwright_token(cluster_lb=...)
  → {"token": "<raw_pingfed_access_token>"}

Step 3 — Discover schema (reads o2://agent-guide first)
  o2_mcp.get_stream_schema(endpoint=..., bearer_token=..., stream="k8s_json",
                            user_prompt="5XX errors for payment-service")
  → {fields: [...], full_text_search_keys: [...], partition_keys: [...]}

Step 4 — Generate SQL (agent uses o2://datafusion-sql + o2://o2-guide)
  SELECT status_code, count(_timestamp) AS total
  FROM   "k8s_json"
  WHERE  kubernetes_namespace_name = 'prod'
    AND  kubernetes_labels_app = 'payment-service'
    AND  CAST(status_code AS INT) >= 500
  GROUP BY status_code
  ORDER BY total DESC
  LIMIT 100

Step 5 — Validate locally (< 10 ms, no network)
  o2_mcp.validate_sql_functions(sql=...)    → all functions valid ✓
  o2_mcp.validate_sql_policy(sql=...)       → no violations ✓

Step 6 — Execute
  o2_mcp.execute_sql(sql=..., endpoint=..., bearer_token=..., time_range="1h")
  → {"success": true, "hits": [...], "total": 47}

Step 7 — If auth_expired:
  super-agent.pingfed_playwright_token(cluster_lb=...)  ← refresh
  retry execute_sql with new token

Step 8 — Present results with context from AGENT.md
```

---

## Configuration

```bash
# .env
O2_ENDPOINT=https://intl.logs.prod.walmart.com   # optional fallback (dev only)
O2_AUTH_TOKEN=                                    # optional fallback (dev only)
O2_ORG_ID=default
O2_MAX_RETRIES=5          # retry loop limit (1-10)
O2_LOG_LEVEL=INFO
FASTMCP_STATELESS_HTTP=1  # required for chatbot/HTTP transport
```

In production, `endpoint` and `bearer_token` are passed **per tool call** by the
super-agent. The env vars are only needed for local development with static credentials.

---

## Running the Server

```bash
# stdio (standard MCP — for Claude Desktop, Cursor, etc.)
python -m src.server

# Streamable HTTP (for chatbot/multi-agent setups)
FASTMCP_STATELESS_HTTP=1 fastmcp run src/server.py --transport streamable-http --port 8000

# With hot reload (development)
FASTMCP_STATELESS_HTTP=1 fastmcp dev src/server.py
```

### MCP Client Config (Claude Desktop)

```json
{
  "mcpServers": {
    "o2_mcp": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/o2_mcp"
    }
  }
}
```

---

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
.venv/bin/python -m pytest tests/ -v

# Run a single test module
.venv/bin/python -m pytest tests/test_sql_policy.py -v

# Type check (optional)
.venv/bin/python -m mypy src/
```

### Adding a New Tool

1. Decide which provider module it belongs in (`query.py`, `validation.py`, `sql_tools.py`, etc.)
2. Add the business logic to `src/tools/` (no FastMCP imports)
3. Add the `@provider.tool("tool_name")` wrapper in the provider module
4. No changes needed to `server.py` — providers are already registered

### Adding a New Resource

1. Add the `.md` file to `data/resources/`
2. Add the path constant to `src/providers/_shared.py`
3. Add the `@provider.resource("o2://your-uri")` function to `src/providers/resources.py`

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `fastmcp` | MCP server framework (tools, resources, prompts) |
| `httpx` | Async HTTP client for OpenObserve API calls |
| `sqlglot` | SQL parser + AST for static analysis and policy checks |
| `pydantic-settings` | Typed config from env vars |
| `structlog` | Structured logging |
| `python-dotenv` | `.env` file loading |
