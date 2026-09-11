"""MongoDB connection using Motor (async driver)."""
import logging
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("backend-api.mongo")

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
        _client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=3000)
        logger.info("mongo_client_created", extra={"event": "mongo_client_created"})
    return _client


def get_db():
    return get_client()[os.getenv("MONGO_DB_NAME", "voiceai_pilot")]
