import os
from asyncio import all_tasks
from contextlib import asynccontextmanager
from os import EX_OK
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

load_dotenv()


@asynccontextmanager
async def lifespan(application: FastAPI):
    try:
        print(f"FastAPI App: {application.__doc__}")
        yield
    except Exception as e:
        # Log the error and any pending tasks
        print(f"Error during shutdown: {e.__traceback__}")
        pending_tasks = [task for task in all_tasks() if not task.done()]
        print(f"Pending tasks during shutdown: {pending_tasks}")
        for task in pending_tasks:
            print(f"- Task:- [{task.get_coro()}]")
    finally:

        print("Forcing application shutdown now.")
        # noinspection PyProtectedMember
        os._exit(EX_OK)  # Forcefully kill the process


app = FastAPI(lifespan=lifespan, root_path="/kazuma")
app.include_router(router)
app.include_router(anilist_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/", tags=["Health Check"])
async def home():
    image_path = os.getenv("HEALTH_PATH")
    print(image_path)
    if not Path(image_path).is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(image_path, media_type="image/png")


@app.get("/count", tags=["Visitor Count"])
async def count():

    return {"count": count_service()}


app.mount("/", app=socket_app)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=6969, reload=True, lifespan="on", timeout_keep_alive=50)
