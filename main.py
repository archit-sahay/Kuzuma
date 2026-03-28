import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.controllers.anilist_controller import router as anilist_router
from src.controllers.socket_controller import socket_app
from src.controllers.spotify_controller import router
from src.services.count_service import count_service
from src.services.socket_service import cleanup_stale_sessions, disconnect_service, message_histories
from src.logger import get_logger

load_dotenv()

logger = get_logger(__name__)

_cleanup_task = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _cleanup_task
    logger.info(f"FastAPI App starting up")
    # Start background session cleanup
    _cleanup_task = asyncio.create_task(cleanup_stale_sessions())
    try:
        yield
    finally:
        logger.info("Application shutting down. Saving active sessions...")
        for sid in list(message_histories.keys()):
            try:
                await disconnect_service(sid)
            except Exception as e:
                logger.error(f"Failed to save session {sid} on shutdown: {e}")
        if _cleanup_task:
            _cleanup_task.cancel()


app = FastAPI(lifespan=lifespan, root_path="/kazuma")
app.include_router(router)
app.include_router(anilist_router)

cors_origins = os.getenv("CORS_ORIGINS", "https://kuzuma.space").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/", tags=["Health Check"])
async def home():
    image_path = os.getenv("HEALTH_PATH")
    logger.info(f"Health check requested, image path: {image_path}")
    if not Path(image_path).is_file():
        logger.warning(f"Image not found at path: {image_path}")
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(image_path, media_type="image/png")


@app.get("/count", tags=["Visitor Count"])
async def count():
    logger.info("Visitor count requested")
    return {"count": await count_service()}


app.mount("/", app=socket_app)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=6969, lifespan="on", timeout_keep_alive=50)
