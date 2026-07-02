"""FastAPI application factory for {{cookiecutter.project_name}}.

Mounts:
  POST /.well-known/agent.json  — A2A Agent Card (served by A2AStarletteApplication)
  POST /a2a                     — A2A message/send endpoint
  GET  /health                  — health check
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.adk.runners import Runner
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
)
from google.adk.artifacts import InMemoryArtifactService

from src.agent.agent import create_agent
from src.config import get_settings

log = logging.getLogger(__name__)

# ── Agent Card ────────────────────────────────────────────────────────────────
# THIS IS WHAT super-agent reads from /.well-known/agent.json at startup.
# Update name, description, and skills to accurately describe your agent.

AGENT_CARD = AgentCard(
    name="{{cookiecutter.agent_name}}",
    description="{{cookiecutter.agent_description}}",
    url=f"http://localhost:{get_settings().agent_port}",
    version="{{cookiecutter.agent_version}}",
    capabilities=AgentCapabilities(
        streaming=False,
        pushNotifications=False,
    ),
    skills=[
        # ── TODO: Replace with your agent's actual skills ─────────────────
        # Each skill.id + skill.description is shown to the orchestrator LLM.
        # Be specific — the LLM uses this to decide when to delegate here.
        AgentSkill(
            id="example_skill",
            name="Example Skill",
            description=(
                "Describe EXACTLY what input this skill expects and what it returns. "
                "Example: 'Analyzes the health of a WCNP namespace given the namespace name. "
                "Returns a structured health report with status, issues, and recommendations.'"
            ),
        ),
    ],
    defaultInputModes=["text/plain"],
    defaultOutputModes=["text/plain"],
)


# ── Application lifespan ──────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    s = get_settings()

    agent, exit_stack = await create_agent()

    # ADK Redis session service (or InMemorySessionService for local dev)
    try:
        from google.adk.sessions import InMemorySessionService
        session_service = InMemorySessionService()
        log.info("Using InMemorySessionService (local dev)")
    except Exception:
        session_service = InMemorySessionService()

    runner = Runner(
        agent=agent,
        app_name="{{cookiecutter.agent_name}}",
        session_service=session_service,
        artifact_service=InMemoryArtifactService(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_card = AGENT_CARD

    # Mount A2A endpoint
    executor = A2aAgentExecutor(runner=runner)
    handler  = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore())
    a2a_app  = A2AStarletteApplication(agent_card=AGENT_CARD, http_handler=handler)
    app.mount("/", a2a_app.build())

    log.info(
        "{{cookiecutter.project_name}} ready — port=%s agent=%s",
        s.agent_port, agent.name,
    )

    yield

    await exit_stack.aclose()
    log.info("{{cookiecutter.project_name}} shut down cleanly")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="{{cookiecutter.project_name}}",
        version="{{cookiecutter.agent_version}}",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "agent": "{{cookiecutter.agent_name}}",
            "version": "{{cookiecutter.agent_version}}",
        }

    return app
