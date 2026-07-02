# valid8-mcp

MCP (Model Context Protocol) server for Walmart's **Valid8** validation platform. Exposes
Canada (CA) and Mexico (MX) validation and data retrieval APIs as MCP tools for use by
any MCP-compatible agent (Google ADK, Super Agent, Claude, Cursor, etc.).

---

## Stage Endpoint

| | |
|--|--|
| **Base URL** | `https://valid8-mcp.stage.walmart.com/` |
| **MCP Protocol** | `https://valid8-mcp.stage.walmart.com/mcp` |
| **Health Check** | `https://valid8-mcp.stage.walmart.com/health` |

No authentication is required to call the MCP server itself — Valid8 API credentials
are managed internally by the server.

---

## Integration Guide (for Super Agent / consuming agents)

### Step 1 — Verify the server is alive

```bash
curl https://valid8-mcp.stage.walmart.com/health
```

Expected:

```json
{"status": "healthy", "version": "1.0.0", "tools": 4, "resources": 2, "prompts": 1}
```

### Step 2 — Discover available tools

```bash
curl https://valid8-mcp.stage.walmart.com/mcp/tools
```

Returns all 4 tools with their names, descriptions, and required parameters.

### Step 3 — Connect your MCP client

Point your MCP client (Google ADK `MCPToolset`, LangChain MCP adapter, or custom client)
at the MCP endpoint:

```
https://valid8-mcp.stage.walmart.com/mcp
```

The client will auto-discover all tools, resources, and prompts. No manual tool
registration is needed.

### Step 4 — Invoke tools via MCP JSON-RPC

All tool calls go to `POST /mcp` using JSON-RPC 2.0 with SSE responses:

```bash
curl -X POST https://valid8-mcp.stage.walmart.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "<tool_name>",
      "arguments": { ... }
    },
    "id": "1"
  }'
```

---

## MCP Tools (4)

### 1. `ca_orchestrated_query` — Canada SKU Validation

Runs an orchestrated query across multiple Canada backend systems (Catalog, IMS, MCSE, PNO, Search) for a given SKU.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sku_id` | string | Yes | Canada SKU identifier |

**Example call:**

```bash
curl -X POST https://valid8-mcp.stage.walmart.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "ca_orchestrated_query",
      "arguments": {"sku_id": "6000199554997"}
    },
    "id": "1"
  }'
```

**Sample response (truncated):**

```json
{
  "success": true,
  "data": {
    "orchestrated_results": {
      "applications": {
        "catalog": {"application": "catalog", "count": 1, "results": [{"is_visible": true, "offer_status": "true", "offer_type": "1P", "sku_id": "6000199554997"}]},
        "ims": {"application": "ims", "success": false, "error": "No pangeaOfferId found"},
        "mcse": {"application": "mcse", "results": [...]},
        "pno": {"application": "pno", "results": [...]},
        "search": {"application": "search", "results": [...]}
      }
    }
  },
  "sku_id": "6000199554997",
  "took_ms": 28500
}
```

---

### 2. `mx_item_visibility_lookup_upc` — Mexico Item Visibility

Looks up item visibility at a specific store by offer ID and banner.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `offer_id` | string | Yes | Item offer ID |
| `banner` | string | Yes | Banner code (e.g. `"WM"`) |
| `store_number` | string | Yes | Store number |

**Example call:**

```bash
curl -X POST https://valid8-mcp.stage.walmart.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "mx_item_visibility_lookup_upc",
      "arguments": {
        "offer_id": "2F1A382F30483E47AD888D0AA01DBDDF",
        "banner": "WM",
        "store_number": "2344"
      }
    },
    "id": "2"
  }'
```

**Sample response:**

```json
{
  "success": true,
  "data": {
    "offerId": "2F1A382F30483E47AD888D0AA01DBDDF",
    "storeNumber": "2344",
    "success": true,
    "upc": "00033554661739"
  },
  "offer_id": "2F1A382F30483E47AD888D0AA01DBDDF",
  "banner": "WM",
  "store_number": "2344",
  "took_ms": 658.9
}
```

---

### 3. `mx_item_status` — Mexico Item Status

Returns detailed item metadata (brand, price, category attributes, images, etc.) for a list of items under a specific banner.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `banner` | string | Yes | Banner code (e.g. `"wm-bd"` for Bodega Aurrera) |
| `items` | list[string] | Yes | List of item IDs |
| `format` | string | No | Output format (default: `"table"`) |

**Example call:**

```bash
curl -X POST https://valid8-mcp.stage.walmart.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "mx_item_status",
      "arguments": {
        "banner": "wm-bd",
        "items": ["00085240100638"]
      }
    },
    "id": "3"
  }'
```

**Sample response (truncated):**

```json
{
  "success": true,
  "data": {
    "banner": "wm-bd",
    "data": {
      "data": {
        "items": [{
          "brand": "Waterwipes",
          "additionalDescription": "Calidad garantizada...",
          "categoryAttributes": {"Aroma": "Sin aroma", "Contenido del Empaque": "1 Paquete con 60 piezas"},
          "correlationIds": {"ean": "0885240100638"}
        }]
      }
    }
  },
  "banner": "wm-bd",
  "items": ["00085240100638"],
  "took_ms": 1200
}
```

---

### 4. `mx_order_dashboard_search` — Mexico Order Dashboard

Searches the Mexico order dashboard. Both parameters are optional — omit them to get all recent orders.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `seller_name` | string | No | Seller name to filter by |
| `time_frame` | string | No | Time window: `"30min"`, `"1h"`, `"24h"` |

**Example call:**

```bash
curl -X POST https://valid8-mcp.stage.walmart.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "mx_order_dashboard_search",
      "arguments": {
        "seller_name": "Bodega Aurrera",
        "time_frame": "30min"
      }
    },
    "id": "4"
  }'
```

**Sample response (truncated):**

```json
{
  "success": true,
  "data": {
    "count": 4613,
    "data": [
      {"ITEM_DESCRIPTION": "Detergente en polvo Roma multiusos biodegradable 1 kg", "ITEM_ID": "00750102600460", "ORDER_COUNT": 70, "UNIT_PRICE": 40},
      {"ITEM_DESCRIPTION": "Huevo blanco San Juan 30 pzas", "ITEM_ID": "00750300055517", "ORDER_COUNT": 69, "UNIT_PRICE": 74}
    ]
  },
  "seller_name": "Bodega Aurrera",
  "time_frame": "30min",
  "took_ms": 2400
}
```

---

## Example User Prompts

These are natural-language prompts a user can type in the chatbot. The LLM agent uses the
Valid8 MCP tools to answer them automatically.

### Canada (CA) Prompts

| Prompt | Tool Used |
|--------|-----------|
| "Is SKU 6000199554997 visible on walmart.ca?" | `ca_orchestrated_query` |
| "Validate Canada SKU 6000202441234" | `ca_orchestrated_query` |
| "Run an OASIS check for SKU 6000199554997" | `ca_orchestrated_query` |
| "What's the catalog and IMS status for this CA SKU: 6000199554997?" | `ca_orchestrated_query` |
| "Check if SKU 6000199554997 is in the search index on Canada" | `ca_orchestrated_query` |
| "Is this Canadian item live? SKU 6000199554997" | `ca_orchestrated_query` |

### Mexico (MX) — Item Visibility Prompts

| Prompt | Tool Used |
|--------|-----------|
| "Is offer 2F1A382F30483E47AD888D0AA01DBDDF visible at WM store 2344?" | `mx_item_visibility_lookup_upc` |
| "Check item visibility for offer ID 2F1A382F30483E47AD888D0AA01DBDDF in Walmart Mexico store 2344" | `mx_item_visibility_lookup_upc` |
| "Look up the UPC for this MX offer: 2F1A382F30483E47AD888D0AA01DBDDF at store 2344" | `mx_item_visibility_lookup_upc` |
| "What's the UPC for offer 2F1A382F at Walmart Mexico store 5678?" | `mx_item_visibility_lookup_upc` |

### Mexico (MX) — Item Status Prompts

| Prompt | Tool Used |
|--------|-----------|
| "Get status of item 00085240100638 in Bodega Aurrera" | `mx_item_status` |
| "What's the item status for 00085240100638 in wm-bd?" | `mx_item_status` |
| "Check these items in Bodega: 00085240100638, 00750102600460" | `mx_item_status` |
| "Is item 00085240100638 active in Walmart Mexico banner wm-bd?" | `mx_item_status` |
| "Show me product details for item 00085240100638 at Bodega Aurrera" | `mx_item_status` |
| "What brand is item 00085240100638 in Bodega?" | `mx_item_status` |

### Mexico (MX) — Order Dashboard Prompts

| Prompt | Tool Used |
|--------|-----------|
| "Show recent orders for Bodega Aurrera in the last 30 minutes" | `mx_order_dashboard_search` |
| "What are the top selling items at Bodega Aurrera right now?" | `mx_order_dashboard_search` |
| "Show me Mexico order dashboard for the last hour" | `mx_order_dashboard_search` |
| "How many orders did Bodega Aurrera get in the last 24 hours?" | `mx_order_dashboard_search` |
| "What are the most ordered grocery items at Bodega in the last 30 min?" | `mx_order_dashboard_search` |
| "Search MX order dashboard — all sellers, last 1 hour" | `mx_order_dashboard_search` |

### Multi-Tool / Follow-Up Prompts

| Prompt | Tools Used |
|--------|------------|
| "Check the status of item 00085240100638 in Bodega and also show me recent orders" | `mx_item_status` + `mx_order_dashboard_search` |
| "Validate CA SKU 6000199554997 and then check if 00085240100638 is active in MX" | `ca_orchestrated_query` + `mx_item_status` |
| "Is offer 2F1A382F visible at store 2344? Also get the item status for 00085240100638 in wm-bd" | `mx_item_visibility_lookup_upc` + `mx_item_status` |

---

## MCP Resources (2)

Resources provide documentation that agents can read at session start for context.

| URI | Name | Description |
|-----|------|-------------|
| `valid8://agent-guide` | Agent Guide | Full workflow, tool selection, and response format documentation |
| `valid8://api-reference` | API Reference | All endpoints with request/response examples |

**Read a resource:**

```bash
curl https://valid8-mcp.stage.walmart.com/mcp/resources/valid8://agent-guide
```

---

## MCP Prompts (1)

| Name | Description |
|------|-------------|
| `valid8_usage` | Quick reference for selecting the right tool based on user intent |

**List prompts:**

```bash
curl https://valid8-mcp.stage.walmart.com/mcp/prompts
```

---

## Common Reference Values

### Mexico Banner Codes

| Code | Name |
|------|------|
| `WM` | Walmart Mexico |
| `wm-bd` | Bodega Aurrera |

### Time Frames (Order Dashboard)

| Value | Meaning |
|-------|---------|
| `30min` | Last 30 minutes |
| `1h` | Last 1 hour |
| `24h` | Last 24 hours |

### Canada SKU Format

SKU IDs are numeric strings, e.g. `"6000199554997"`.

---

## REST Endpoints (HTTP mode)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/mcp` | MCP protocol (streamable HTTP, JSON-RPC 2.0) |
| GET | `/` | Server info (name, version, tool/resource/prompt counts) |
| GET | `/health` | Health check |
| GET | `/health/liveness` | Liveness probe (Kubernetes) |
| GET | `/health/readiness` | Readiness probe (Kubernetes) |
| GET | `/mcp/tools` | List all tools |
| GET | `/mcp/resources` | List all resources |
| GET | `/mcp/resources/{uri}` | Read a specific resource's content |
| GET | `/mcp/prompts` | List all prompts |

---

## Authentication

Valid8 uses **API key + tenant header** authentication to talk to the upstream Valid8 platform:
- `X-API-Key` — configured via `VALID8_API_KEY` environment variable (managed in Akeyless)
- `X-Tenant` — set automatically per tool (`ca` for Canada, `mx` for Mexico)

**Consuming agents do not need any credentials** — the MCP server handles authentication
internally. Just call the MCP endpoint.

---

## Architecture

Follows the same architecture as `o2_mcp`:
- **FastMCP** server with `LocalProvider` modules for tools, resources, and prompts
- **Stateless HTTP** transport for production (`POST /mcp`), **stdio** for local/CLI
- **Custom REST routes** for health checks and introspection

---

## Local Development

### Requirements

- Python 3.11+

### Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -e .
```

### Configuration

Copy `.env.example` to `.env` and set:

```bash
VALID8_API_KEY=your-api-key-here
VALID8_BASE_URL=https://intl-valid8-stage.walmart.com
```

Optional: `VALID8_TIMEOUT`, `VALID8_VERIFY_SSL`, `VALID8_LOG_LEVEL`.

### Run

```bash
# stdio (Claude Desktop, Cursor)
python -m src.server

# HTTP (production mode)
uvicorn app:app --host 0.0.0.0 --port 8015 --workers 2
```

### Docker

```bash
docker build -t valid8-mcp .
docker run -p 8015:8015 --env-file .env valid8-mcp
```

### Tests

```bash
pytest
```

---

## Error Responses

All tools return a consistent structure on failure:

```json
{
  "success": false,
  "error": "Connection error: Cannot connect to https://...",
  "banner": "wm-bd",
  "items": ["00085240100638"]
}
```

| Error Type | Meaning | Action |
|------------|---------|--------|
| `Connection error` | Valid8 backend unreachable | Retry after a moment |
| `Valid8 API error (401)` | Invalid or missing API key | Check VALID8_API_KEY in Akeyless |
| `Valid8 API error (4xx/5xx)` | Bad request or server error | Check the error message for details |
