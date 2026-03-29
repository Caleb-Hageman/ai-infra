import time
from fastapi import Request, Depends
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.background import BackgroundTasks

from app.services.usage import log_api_usage


import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")


class ApiUsageMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger.info("hello")

        start_time = time.time()

        # Create background tasks container
        background_tasks = BackgroundTasks()

        response = await call_next(request)

        latency_ms = int((time.time() - start_time) * 1000)

        team_id = getattr(request.state, "team_id", None)
        api_key_id = getattr(request.state, "api_key_id", None)

        logger.info(json.dumps({
            "event": "api_usage",
            "team_id": str(team_id),
            "api_key_id": str(api_key_id),
            "path": request.url.path,
            "latency_ms": latency_ms,
        }))

        background_tasks.add_task(
            log_api_usage,
            team_id,
            api_key_id,
            request.url.path,
            start_time,
            latency_ms,
        )

        response.background = background_tasks

        return response