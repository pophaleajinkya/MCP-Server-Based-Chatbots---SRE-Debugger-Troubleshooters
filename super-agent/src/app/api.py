"""Lite agent — API routes, lifespan, and app factory.

Provides:
  router      — FastAPI APIRouter with /query and /query_api
  create_app  — builds and returns the configured FastAPI application
"""

import logging
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import get_settings
from app.mcp.client import MCPPool, MCPSession, load_mcp_servers
from app.services.llm import run_agent_claude, run_agent_openai

log = logging.getLogger(__name__)

_AGENT_DESCRIPTION = """\
WCNP Health Agent — provides detailed health reports for any Kubernetes namespace
or namespace + app combination on WCNP clusters. Runs 17 parallel health checks
across compute, mesh, pods, secrets, and configuration using live Prometheus data.

You are the WCNP Health Agent, a specialized Kubernetes health intelligence assistant
for Walmart's Cloud Native Platform (WCNP).

Your primary job is to run detailed health diagnostics on any given Kubernetes
namespace, or a specific app within a namespace, and return a structured health report
with clear statuses, anomaly explanations, and Grafana links for investigation.

CHECKS PERFORMED:
1. CPU CHECK — Fleet CPU health (last 10 min). Uses fleet p95 as signal. Result contains:
   - `high_cpu_in`: plain-language list of affected components (e.g. "app CPU: p95 at 91% exceeds unhealthy threshold"). Read this first.
   - `app_cpu` / `proxy_cpu`: fleet stats (mean, median, p95, max) + status + thresholds.
   - Thresholds are configured in Redis (metric:wcnp) — read from result `thresholds` field, not hardcoded.
2. MEMORY CHECK — memory working set as % of limit; flags >95% app / >80% Istio; detects OOMKill.
3. CONTAINER RESTARTS — restarts in last 1h; any = warning, >1 = unhealthy; CrashLoopBackOff detection.
4. NODE CPU — checks CPU on nodes hosting the app's pods; flags >80%; baseline spike detection.
5. NODE PROBLEM DETECTOR — active node-level problems (Azure only); kernel, disk, network issues.
6. PODS CHECK (5 parallel sub-checks):
   a. REPLICA READINESS — desired vs. ready replicas; failure reason per unavailable pod.
   b. SCALE EVENTS — unexpected scale-up/down vs. 6-hour rolling average.
   c. POD AGE DISTRIBUTION — identifies very young or very old pods.
   d. POD RESCHEDULING — detects node evictions in last 60 min.
   e. ROLLOUT DETECTION — rolling updates via label changes over 7-day window.
7. EXTERNAL SECRETS — Akeyless ExternalSecret status; auth, path, connectivity issues.
8. CCM CONFIGMAP CHANGE DETECTION — CCM config push detection; covers canary and primary.
ISTIO SERVICE MESH CHECKS (all compare current vs. 6-hour rolling baseline):
9.  CLIENT SUCCESS RATE — outbound non-5xx ratio; flags <95%.
10. SERVER SUCCESS RATE — inbound non-5xx ratio; reports error rate %.
11. TRAFFIC SPIKE DETECTION — volume spikes; 4xx/5xx breakdown; rollout correlation.
12. CLIENT LATENCY P95 — outbound P95 vs. baseline; Grafana link.
13. SERVER LATENCY P95 — inbound P95 vs. baseline; distinguishes app vs. dependency slowness.
14. CLIENT RETRIES — Envoy retry count in last 5 min; baseline spike comparison.
15. RATE LIMITING DETECTION — Istio ingress rate-limit % blocked vs. allowed.

Always returns structured results with ✅ healthy ⚠️ warning 🔴 degraded ❌ error
and Grafana dashboard URLs for investigation.\
"""


# ── Schemas ───────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description="Natural language question for the WCNP health agent.",
    )
    session_id: str | None = Field(
        None,
        description="Optional session identifier. A UUID is generated if omitted.",
    )


class QueryResponse(BaseModel):
    response:   str = Field(..., description="Agent's answer.")
    session_id: str = Field(..., description="Session identifier for this request.")


# ── Routes ────────────────────────────────────────────────────────────────────

router = APIRouter(tags=["agent"])


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest, request: Request) -> QueryResponse:
    return await _handle_query(req, request.app.state.mcp, request.app.state.llm)


@router.post(
    "/query_api",
    response_model=QueryResponse,
    summary=(
        "Query WCNP Kubernetes Health, Deployment & Routing Insights. "
        "Use this endpoint to search and retrieve information about applications, "
        "deployments, canary status, health probes, CNAME/GSLB routes, and Kubernetes "
        "metadata across WCNP clusters. Supports multi-tenant, multi-region troubleshooting "
        "for SRE and DevOps teams."
    ),
)
async def query_api(req: QueryRequest, request: Request) -> QueryResponse:
    return await _handle_query(req, request.app.state.mcp, request.app.state.llm)


async def _handle_query(req: QueryRequest, mcp, client: httpx.AsyncClient) -> QueryResponse:
    session_id = req.session_id or str(uuid.uuid4())
    try:
        if get_settings().claude_is_primary_llm:
            response = await run_agent_claude(mcp, client, req.query)
        else:
            response = await run_agent_openai(mcp, client, req.query)
    except httpx.HTTPStatusError as exc:
        log.error("LLM error: %s — %s", exc.response.status_code, exc.response.text[:300])
        raise HTTPException(
            status_code=502,
            detail=f"LLM error {exc.response.status_code}: {exc.response.text[:200]}",
        )
    except Exception as exc:
        log.exception("Agent error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return QueryResponse(response=response, session_id=session_id)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    log.info("Starting A2A Query Agent (lite) on http://%s:%d", s.agent_host, s.agent_port)

    # verify=False is intentional: internal Walmart gateway services use self-signed certs
    _http_kwargs = {"follow_redirects": True, "verify": False}  # noqa: S501
    http_client = httpx.AsyncClient(**_http_kwargs)
    llm_client  = httpx.AsyncClient(**_http_kwargs)

    server_configs = await load_mcp_servers()
    sessions       = [MCPSession(http_client, cfg.url, cfg.name, headers=cfg.headers) for cfg in server_configs]
    mcp_pool       = MCPPool(sessions)

    try:
        await mcp_pool.connect()
    except Exception as exc:
        log.warning("MCP pool connect failed (%s) — running without tools", exc)

    app.state.mcp  = mcp_pool
    app.state.http = http_client
    app.state.llm  = llm_client

    log.info("POST /query     — ask the agent")
    log.info("POST /query_api — MAOF alias")
    log.info("Active LLM — %s", f"Claude ({s.claude_model})" if s.claude_is_primary_llm else f"OpenAI ({s.openai_model})")

    yield

    await http_client.aclose()
    await llm_client.aclose()
    log.info("Shutdown complete")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    application = FastAPI(
        title="A2A Query Agent",
        description="WCNP health agent with MCP tools + Element Gateway LLM",
        version="1.2.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(router)

    return application
