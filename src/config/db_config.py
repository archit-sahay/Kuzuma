import os
from contextlib import asynccontextmanager

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")  # e.g., "mongodb://localhost:27017"

client = AsyncIOMotorClient(
    MONGODB_URL,
    tls=True,
    tlsAllowInvalidCertificates=True
)
db = client.get_database()  # Optionally specify db name here


@asynccontextmanager
# Dependency for FastAPI to get db instance
async def get_db():
    try:
        yield db
    finally:
        pass  # Motor client handles connection pooling automatically
