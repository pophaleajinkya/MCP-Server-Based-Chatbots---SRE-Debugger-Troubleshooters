"""Additional unit tests for health router — covers liveness endpoint (line 54)."""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestLivenessEndpoint:
    def test_liveness_returns_ok(self):
        from app.routers.health import router
        app = FastAPI()
        app.include_router(router)
        # The liveness endpoint is defined but may conflict with ready due to function name reuse.
        # Let's test it exists and returns 200.
        client = TestClient(app)
        resp = client.get("/liveness")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
