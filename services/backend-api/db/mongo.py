"""MongoDB connection using Motor (async driver) with robust in-memory fallback."""
from __future__ import annotations

from copy import deepcopy
import logging
import os
import uuid
from datetime import timezone
from typing import Any

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

logger = logging.getLogger("backend-api.mongo")

_client: AsyncIOMotorClient | None = None
_use_memory_fallback: bool = False
_mem_db: MemoryDatabase | None = None


class MemoryCursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def sort(self, key: str, direction: int = 1):
        self._docs = sorted(
            self._docs,
            key=lambda d: d.get(key, 0) if d.get(key) is not None else 0,
            reverse=(direction == -1),
        )
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        if length is not None:
            return [dict(d) for d in self._docs[:length]]
        return [dict(d) for d in self._docs]


class UpdateResult:
    def __init__(self, matched_count: int, modified_count: int):
        self.matched_count = matched_count
        self.modified_count = modified_count


class DeleteResult:
    def __init__(self, deleted_count: int):
        self.deleted_count = deleted_count


def _get_path(doc: dict, dotted_key: str) -> Any:
    """Resolve a dotted path (e.g. "consent.ai_interview") like Mongo does."""
    value: Any = doc
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _set_path(doc: dict, dotted_key: str, value: Any) -> None:
    target = doc
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            child = {}
            target[part] = child
        target = child
    target[parts[-1]] = value


def _unset_path(doc: dict, dotted_key: str) -> None:
    target = doc
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            return
        target = child
    target.pop(parts[-1], None)


def _matches(doc: dict, query: dict) -> bool:
    for k, v in query.items():
        if k == "$or":
            if not any(_matches(doc, branch) for branch in v):
                return False
            continue
        if isinstance(v, dict):
            doc_val = _get_path(doc, k)
            for op, op_val in v.items():
                if op == "$gt" and not (doc_val is not None and doc_val > op_val):
                    return False
                if op == "$gte" and not (doc_val is not None and doc_val >= op_val):
                    return False
                if op == "$lt" and not (doc_val is not None and doc_val < op_val):
                    return False
                if op == "$lte" and not (doc_val is not None and doc_val <= op_val):
                    return False
                if op == "$in" and doc_val not in op_val:
                    return False
                if op == "$exists":
                    exists = _get_path(doc, k) is not None if "." in k else k in doc
                    if exists != bool(op_val):
                        return False
            continue
        if _get_path(doc, k) != v:
            return False
    return True


class MemoryCollection:
    def __init__(self, name: str):
        self.name = name
        self._docs: dict[Any, dict] = {}

    async def create_index(self, *args, **kwargs):
        return "ok"

    async def find_one(
        self, query: dict, projection: dict | None = None
    ) -> dict | None:
        for doc in self._docs.values():
            if _matches(doc, query):
                res = dict(doc)
                if projection and projection == {"_id": 1}:
                    return {"_id": res.get("_id")}
                return res
        return None

    async def insert_one(self, document: dict) -> None:
        doc_id = document.get("_id") or uuid.uuid4().hex
        if doc_id in self._docs:
            raise ValueError(f"duplicate in-memory _id for {self.name}")
        stored = dict(document)
        stored["_id"] = doc_id
        self._docs[doc_id] = stored

    async def update_one(
        self, query: dict, update: dict, upsert: bool = False
    ) -> UpdateResult:
        matched = 0
        modified = 0
        for doc_id, doc in list(self._docs.items()):
            if _matches(doc, query):
                matched += 1
                before = deepcopy(doc)
                if "$set" in update:
                    for sk, sv in update["$set"].items():
                        _set_path(doc, sk, sv)
                if "$unset" in update:
                    for uk in update["$unset"]:
                        _unset_path(doc, uk)
                if "$push" in update:
                    for pk, pv in update["$push"].items():
                        values = _get_path(doc, pk)
                        if not isinstance(values, list):
                            values = []
                            _set_path(doc, pk, values)
                        values.append(pv)
                modified = int(doc != before)
                break
        if matched == 0 and upsert:
            new_doc = {
                key: value
                for key, value in query.items()
                if not key.startswith("$") and not isinstance(value, dict)
            }
            for sk, sv in update.get("$setOnInsert", {}).items():
                _set_path(new_doc, sk, sv)
            if "$set" in update:
                for sk, sv in update["$set"].items():
                    _set_path(new_doc, sk, sv)
            if "$push" in update:
                for pk, pv in update["$push"].items():
                    _set_path(new_doc, pk, [pv])
            doc_id = new_doc.get("_id") or uuid.uuid4().hex
            new_doc["_id"] = doc_id
            self._docs[doc_id] = new_doc
            matched = 1
            modified = 1
        return UpdateResult(matched, modified)

    async def delete_one(self, query: dict) -> DeleteResult:
        for doc_id, doc in list(self._docs.items()):
            if _matches(doc, query):
                del self._docs[doc_id]
                return DeleteResult(1)
        return DeleteResult(0)

    def find(self, query: dict) -> MemoryCursor:
        matched = [doc for doc in self._docs.values() if _matches(doc, query)]
        return MemoryCursor(matched)


class MemoryDatabase:
    def __init__(self):
        self._collections: dict[str, MemoryCollection] = {}

    def __getattr__(self, name: str) -> MemoryCollection:
        if name not in self._collections:
            self._collections[name] = MemoryCollection(name)
        return self._collections[name]

    def __getitem__(self, name: str) -> MemoryCollection:
        return getattr(self, name)

    async def command(self, cmd: str) -> dict:
        return {"ok": 1.0}


def get_memory_db() -> MemoryDatabase:
    global _mem_db
    if _mem_db is None:
        _mem_db = MemoryDatabase()
    return _mem_db


def set_fallback_mode(enabled: bool = True) -> None:
    global _use_memory_fallback
    _use_memory_fallback = enabled


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
        _client = AsyncIOMotorClient(
            url,
            serverSelectionTimeoutMS=3000,
            tz_aware=True,
            tzinfo=timezone.utc,
        )
        logger.info("mongo_client_created", extra={"event": "mongo_client_created"})
    return _client


def get_db():
    global _use_memory_fallback
    if _use_memory_fallback:
        return get_memory_db()
    try:
        return get_client()[os.getenv("MONGO_DB_NAME", "voiceai_pilot")]
    except Exception:
        return get_memory_db()


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
