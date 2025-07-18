import socketio
from src.logger import get_logger

log = get_logger(__name__)

sio = None


def create_socketio_app():
    global sio
    try:
        if sio is None:
            log.info('Creating Socket IO App')
            sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=[])
        return sio
    except Exception as e:
        log.error(f"Error while creating socketio app: ", exc_info=e.__traceback__)
        raise RuntimeError(f"Error while getting socketio client instance: {e}")
