import asyncio
from datetime import datetime
import json
import socketio
from dotenv import load_dotenv
from src.logger import get_logger
from src.config.socket_config import create_socketio_app
from src.services.socket_service import message_service, disconnect_service, start_service

load_dotenv()

sio = create_socketio_app()
log = get_logger(__name__)


socket_app = socketio.ASGIApp(sio)


@sio.event
async def connect(sid, environ):
    log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Connection Request Received from Socket ID: [{sid}] and environ: [{environ}]")


@sio.event
async def start(sid, data):
    log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Start sent by [{json.loads(data)["name"]}] => [{json.loads(data)}]")
    await start_service(sid, data)


@sio.event
async def message(sid, data):
    log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Message Received from Socket ID: [{sid}] and data: [{data}]")
    await message_service(sid, json.loads(data)["text"])


@sio.event
async def disconnect(sid):
    log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Disconnect Request Received from Socket ID: [{sid}]")
    await disconnect_service(sid)
