"""A2A Health Agent — entry point (ADK-native).

Run:
    python main.py
    uvicorn main:app --host 0.0.0.0 --port 8001 --reload
"""

import uvicorn

from app.config import get_settings
from app.factory import create_app
from app.logging import setup_logging

setup_logging()

app = create_app()

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run("main:app", host=s.agent_host, port=s.agent_port, reload=False, log_level="info")
