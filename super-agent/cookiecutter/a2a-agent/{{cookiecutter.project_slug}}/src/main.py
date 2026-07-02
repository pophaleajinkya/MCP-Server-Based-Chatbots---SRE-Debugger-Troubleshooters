"""Entry point for {{cookiecutter.project_name}}."""

import logging
import uvicorn
from src.app.factory import create_app
from src.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = create_app()

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run(
        "src.main:app",
        host=s.agent_host,
        port=s.agent_port,
        reload=True,
    )
