from datetime import datetime
import json
import socketio
from dotenv import load_dotenv
from src.logger import get_logger
from src.services.socket_service import message_service, disconnect_service, start_service, sio
from src.utils.rate_limiter import rate_limiter

load_dotenv()

log = get_logger(__name__)

MAX_MESSAGE_LENGTH = 2000

socket_app = socketio.ASGIApp(sio)


@sio.event
async def connect(sid, environ):
    # Log only essential info, not the entire environ dict
    client_ip = environ.get("HTTP_X_REAL_IP", environ.get("REMOTE_ADDR", "unknown"))
    log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Connection from [{sid}] IP: [{client_ip}]")


@sio.event
async def start(sid, data):
    try:
        parsed = json.loads(data) if isinstance(data, str) else data
        name = parsed.get("name", "Anonymous")
        log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Start sent by [{name}]")
        await start_service(sid, data)
    except (json.JSONDecodeError, TypeError) as e:
        log.warning(f"Invalid start data from {sid}: {e}")
        await sio.emit("message", {"text": "Hmm, couldn't read that. Try refreshing?"}, to=sid)


@sio.event
async def message(sid, data):
    # Parse safely
    try:
        parsed = json.loads(data) if isinstance(data, str) else data
        text = parsed.get("text", "").strip()
    except (json.JSONDecodeError, TypeError, AttributeError):
        log.warning(f"Invalid message from {sid}: {data}")
        return

    # Validate
    if not text:
        return

    if len(text) > MAX_MESSAGE_LENGTH:
        await sio.emit("message", {"text": f"That's a bit long! Keep it under {MAX_MESSAGE_LENGTH} characters."}, to=sid)
        return

    # Rate limit
    if not rate_limiter.is_allowed(sid):
        await sio.emit("message", {"text": "Easy there! You're sending messages too fast. Give me a sec."}, to=sid)
        return

    log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Message from [{sid}]: [{text[:100]}]")
    await message_service(sid, text)


@sio.event
async def disconnect(sid):
    log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Disconnect from [{sid}]")
    rate_limiter.cleanup(sid)
    await disconnect_service(sid)
