# Signal MCP Server

MCP server for Walmart International **Signal** platform — exposes app inventory
suggestions, metadata filters, and OE (Operational Excellence) reports as MCP
tools for use by any MCP-compatible agent (Google ADK, Claude, Cursor, etc.).

> **MCP Endpoint (Stage):** `https://signal-mcp.stage.walmart.com/mcp`
> **Transport:** Streamable HTTP (stateless)
> **Authentication:** None required

---

## Architecture

```
Tool providers (MCP tools)  →  Service layer  →  HTTP client  →  Signal REST API
     ↓                                                              ↑
  FastMCP("signal")                                        accept: application/json
```

Design philosophy — **70% prompt / 30% tool**:
- Tools call Signal APIs and return structured data
- Tool descriptions + AGENT.md teach the agent which tool to pick

---

## Quick Validation

```bash
# Server info (should return tools: 4, resources: 2, prompts: 1)
curl https://signal-mcp.stage.walmart.com/

# Health check
curl https://signal-mcp.stage.walmart.com/health

# Readiness (returns 503 if cache not populated yet)
curl https://signal-mcp.stage.walmart.com/health/readiness
```

### Validate via Super Agent `/mcp/validate`

```bash
curl -X POST https://<super-agent-host>/mcp/validate \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://signal-mcp.stage.walmart.com/mcp",
    "transport": "streamable_http"
  }'
```

---

## MCP Server Connection

| Setting | Value |
|---------|-------|
| **URL** | `https://signal-mcp.stage.walmart.com/mcp` |
| **Transport** | `streamable_http` |
| **Headers** | None required |

---

## Tools (4)

### 1. `get_app_inventory_suggestions`

Fetches all application inventory suggestions from Signal.

| Property | Value |
|----------|-------|
| **Parameters** | None |
| **Returns** | Dict with 1,075+ app keys, each mapping to a list of service suggestions |

**MCP call:**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "get_app_inventory_suggestions",
    "arguments": {}
  }
}
```

**curl:**

```bash
curl -X POST https://signal-mcp.stage.walmart.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_app_inventory_suggestions","arguments":{}}}'
```

**Sample response (inside SSE `data:` line):**

```json
{
  "success": true,
  "data": {
    "wcp-profile-service": ["wcp-profile-service-intl-prod", "..."],
    "cam-binq-api": ["rfs-binq-api"],
    "...": "..."
  },
  "took_ms": 1986.5
}
```

---

### 2. `get_app_metadata_filters`

Fetches available metadata filter options for applications.

| Property | Value |
|----------|-------|
| **Parameters** | None |
| **Returns** | Dict with `orgNames` (list) and `metrics` (list) |

**MCP call:**

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "get_app_metadata_filters",
    "arguments": {}
  }
}
```

**curl:**

```bash
curl -X POST https://signal-mcp.stage.walmart.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_app_metadata_filters","arguments":{}}}'
```

**Sample response:**

```json
{
  "success": true,
  "data": {
    "orgNames": [
      { "value": "US OMNI AND PLATFORMS TECH", "label": "US OMNI AND PLATFORMS TECH" },
      "..."
    ],
    "metrics": ["..."]
  },
  "took_ms": 2287.6
}
```

---

### 3. `get_oe_report_certified`

Fetches OE report for WCNP **certified** applications.

| Property | Value |
|----------|-------|
| **Parameters** | `tr_product` (string, default: `"All"`), `apm_id` (string, default: `"All"`) |
| **Returns** | Dict with `data` key containing a list of certified app records |

**MCP call:**

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "get_oe_report_certified",
    "arguments": {
      "tr_product": "All",
      "apm_id": "All"
    }
  }
}
```

**curl:**

```bash
curl -X POST https://signal-mcp.stage.walmart.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_oe_report_certified","arguments":{"tr_product":"All","apm_id":"All"}}}'
```

**Sample response:**

```json
{
  "success": true,
  "data": {
    "data": [
      {
        "id": 302,
        "tr_product": 1043,
        "apm_id": "APM0006877",
        "market": "Canada, Mexico",
        "namespace": "wakanda-killmonger-api",
        "application": "km-api-amend-rsrv-intl-prod",
        "cluster": "scus-prod-a17, useast-prod-az-331",
        "sr_name": "KILLMONGER-API-AMEND-RESERVATION",
        "sr_env": "prod",
        "validation": "Certified",
        "tier": "Tier 0",
        "app_type": "Rest",
        "...": "..."
      }
    ]
  },
  "tr_product": "All",
  "apm_id": "All",
  "took_ms": 2031.6
}
```

**Record fields:** `id`, `tr_product`, `apm_id`, `market`, `namespace`, `application`, `cluster`, `sr_name`, `sr_env`, `git_link`, `app_poc`, `app_manager`, `jira`, `xmatter_group`, `comment`, `validation`, `tier`, `app_type`, `dl`, `slack`, `managed_services`, `business`, `infra`, `env`, `updated_by`, `updated_time`, `incident_response_playbook`, `architecture_diagram`, `contingency_playbook`, `custom_dashboard`, `third_party_dependency`, `holiday_specific_activities`, `domain`, `holiday_signoff`, `excluded_checks`

---

### 4. `get_oe_report_not_certified`

Fetches OE report for WCNP **not-certified** applications.

| Property | Value |
|----------|-------|
| **Parameters** | `tr_product` (string, default: `"All"`), `apm_id` (string, default: `"All"`) |
| **Returns** | Dict with `data` key containing a list of not-certified app records (same schema as certified) |

**MCP call:**

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "get_oe_report_not_certified",
    "arguments": {
      "tr_product": "All",
      "apm_id": "All"
    }
  }
}
```

**curl:**

```bash
curl -X POST https://signal-mcp.stage.walmart.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_oe_report_not_certified","arguments":{"tr_product":"All","apm_id":"All"}}}'
```

**Sample response:**

```json
{
  "success": true,
  "data": {
    "data": [
      {
        "id": 285,
        "tr_product": 1014,
        "apm_id": "APM0015885",
        "namespace": "ca-fin-capital-managment",
        "application": "frontend",
        "validation": "Not Started",
        "tier": "Need to identify",
        "...": "..."
      }
    ]
  },
  "tr_product": "All",
  "apm_id": "All",
  "took_ms": 4942.0
}
```

> **Note:** This endpoint returns ~32,000 records (~30 MB). Response time is ~5–7 seconds.

---

## Resources (2)

| URI | Description |
|-----|-------------|
| `signal://agent-guide` | Full agent guide — workflow, tool selection, response format |
| `signal://api-reference` | API reference with all endpoint details and payload formats |

## Prompt (1)

| Name | Description |
|------|-------------|
| `signal_usage` | Quick-reference for selecting the right Signal tool based on user intent |

---

## Response Format

All tools return a consistent structure:

```json
{
  "success": true,
  "data": { "..." },
  "took_ms": 1234.5
}
```

On error:

```json
{
  "success": false,
  "error": "Signal API error (500): Internal Server Error",
  "status_code": 500
}
```

---

## REST Introspection Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/mcp` | MCP protocol (streamable HTTP) |
| GET | `/` | Server info with tool/resource/prompt counts |
| GET | `/health` | Health check (startup probe) |
| GET | `/health/liveness` | Liveness probe |
| GET | `/health/readiness` | Readiness probe |
| GET | `/mcp/tools` | List all 4 tools with descriptions |
| GET | `/mcp/resources` | List all 2 resources with URIs |
| GET | `/mcp/resources/{uri}` | Read resource content |
| GET | `/mcp/prompts` | List the prompt |

---

## Example User Prompts

When the Signal MCP server is connected to an agent (Super Agent, ADK agent, etc.), users can ask natural language questions. The agent will automatically select the right tool.

### App Inventory

| Prompt | Tool Used |
|--------|-----------|
| "Show me all app inventory suggestions" | `get_app_inventory_suggestions` |
| "What apps are in the Signal inventory?" | `get_app_inventory_suggestions` |
| "List all application suggestions from Signal" | `get_app_inventory_suggestions` |
| "What services are associated with the ca-cart-services app?" | `get_app_inventory_suggestions` |
| "Find inventory suggestions for the wakanda namespace apps" | `get_app_inventory_suggestions` |

### App Metadata & Filters

| Prompt | Tool Used |
|--------|-----------|
| "What metadata filters are available?" | `get_app_metadata_filters` |
| "Show me the org names and metrics from Signal" | `get_app_metadata_filters` |
| "What filter options can I use to search for applications?" | `get_app_metadata_filters` |
| "List all organization names in Signal" | `get_app_metadata_filters` |
| "What metrics does Signal track for applications?" | `get_app_metadata_filters` |

### OE Reports — Certified

| Prompt | Tool Used |
|--------|-----------|
| "Show me all certified OE applications" | `get_oe_report_certified` |
| "Which apps are WCNP certified?" | `get_oe_report_certified` |
| "Get the OE report for certified apps" | `get_oe_report_certified` |
| "Show certified apps for APM ID APM0006877" | `get_oe_report_certified` (with `apm_id` filter) |
| "How many Tier 0 apps are certified?" | `get_oe_report_certified` |
| "List all certified applications in the Canada market" | `get_oe_report_certified` |
| "What is the certification status of apps in namespace wakanda-killmonger-api?" | `get_oe_report_certified` |

### OE Reports — Not Certified

| Prompt | Tool Used |
|--------|-----------|
| "Show me apps that are not yet certified" | `get_oe_report_not_certified` |
| "Which applications have not started OE certification?" | `get_oe_report_not_certified` |
| "Get the not-certified OE report" | `get_oe_report_not_certified` |
| "How many apps still need WCNP certification?" | `get_oe_report_not_certified` |
| "List non-certified apps for product 1014" | `get_oe_report_not_certified` (with `tr_product` filter) |
| "What apps are missing incident response playbooks?" | `get_oe_report_not_certified` |

### Comparative / Cross-tool

| Prompt | Tools Used |
|--------|-----------|
| "Compare the number of certified vs not-certified apps" | `get_oe_report_certified` + `get_oe_report_not_certified` |
| "What percentage of WCNP apps are certified?" | `get_oe_report_certified` + `get_oe_report_not_certified` |
| "Show me the OE readiness summary across all markets" | `get_oe_report_certified` + `get_oe_report_not_certified` |
| "For app wakanda-killmonger-api, show inventory suggestions and certification status" | `get_app_inventory_suggestions` + `get_oe_report_certified` |

---

## Stage Validation Results (April 16, 2026)

| Tool | Status | Response Time | Data Volume |
|------|--------|---------------|-------------|
| `get_app_inventory_suggestions` | **200 OK** | ~2.0s | 1,075 apps |
| `get_app_metadata_filters` | **200 OK** | ~2.3s | 5,000 org names, 94 metrics |
| `get_oe_report_certified` | **200 OK** | ~2.0s | 2,015 records |
| `get_oe_report_not_certified` | **200 OK** | ~4.9s | 32,458 records |

---

## Setup (Local Development)

```bash
# Clone
git clone https://gecgithub01.walmart.com/intl-ecomm-svcs/ADK_Signal_MCP.git
cd ADK_Signal_MCP

# Create virtualenv and install deps
uv sync          # or: pip install -e .

# Configure
cp .env.example .env
# Edit .env with your settings (defaults work for most cases)
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SIGNAL_BASE_URL` | `https://signal-api.walmart.com` | Signal API base URL |
| `SIGNAL_TIMEOUT` | `60` | HTTP timeout in seconds |
| `SIGNAL_VERIFY_SSL` | `true` | Verify TLS certificates |
| `SIGNAL_LOG_LEVEL` | `INFO` | Logging level |

### Run

**stdio (standard MCP transport):**
```bash
python -m src.server
# or: signal-mcp
```

**HTTP (stateless, for deployment):**
```bash
uvicorn app:app --host 0.0.0.0 --port 8020 --workers 2
# or: signal-mcp-server
```

**Docker:**
```bash
docker build -t signal-mcp .
docker run -p 8020:8020 signal-mcp
```

### Tests

```bash
pytest                    # run all tests (19 tests)
pytest --cov=src          # with coverage
pytest tests/test_service.py -v  # specific test file
```

---

## Project Structure

```
ADK_Signal_MCP/
├── app.py                    # ASGI entry point (uvicorn)
├── src/
│   ├── server.py             # FastMCP server + provider registration
│   ├── config.py             # pydantic-settings configuration
│   ├── http_client.py        # Async HTTP client (httpx)
│   ├── providers/
│   │   ├── _shared.py        # Singleton client/service, doc cache
│   │   ├── inventory_tools.py # get_app_inventory_suggestions
│   │   ├── metadata_tools.py  # get_app_metadata_filters
│   │   ├── oe_report_tools.py # get_oe_report_certified, get_oe_report_not_certified
│   │   └── resources.py       # signal:// MCP resources + prompt
│   ├── services/
│   │   └── signal_service.py  # Service layer wrapping HTTP client
│   └── utils/
│       └── logging.py         # Centralized logging setup
├── data/
│   ├── resources/
│   │   ├── AGENT.md           # Agent guide (signal://agent-guide)
│   │   └── api_reference.md   # API reference (signal://api-reference)
│   └── prompts/
│       └── signal_guide.md    # Tool selection prompt
├── tests/                     # 19 unit tests
├── Dockerfile                 # Multi-stage: build → sonar → runtime
├── kitt.yml                   # KITT deployment (dev/stage)
├── kitt-stageGates.yml        # Pre-deploy testing gates
├── .looper.yml                # CI/CD test flows
├── pyproject.toml             # Dependencies (hatchling)
├── entrypoint.sh              # Docker entrypoint
└── sonar-project.properties   # SonarQube config
```

---

## Contact

| | |
|---|---|
| **Repo** | https://gecgithub01.walmart.com/intl-ecomm-svcs/ADK_Signal_MCP |
| **Team** | IntlSRE |
| **Slack** | `#gen-ai-ci-cd-alerts` |
