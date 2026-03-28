import os
import socketio
from src.logger import get_logger

log = get_logger(__name__)

sio = None


def create_socketio_app():
    global sio
    try:
        if sio is None:
            cors_origins = os.getenv("CORS_ORIGINS", "https://kuzuma.space").split(",")
            log.info(f'Creating Socket IO App with CORS origins: {cors_origins}')
            sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=cors_origins)
        return sio
    except Exception as e:
        log.error(f"Error while creating socketio app: ", exc_info=e.__traceback__)
        raise RuntimeError(f"Error while getting socketio client instance: {e}")
