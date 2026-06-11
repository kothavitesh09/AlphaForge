from datetime import datetime, timezone
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def serialize(document: dict | None) -> dict | None:
    if not document:
        return None
    item = dict(document)
    item["id"] = str(item.pop("_id"))
    return item


class MongoRepository:
    def __init__(self, db: AsyncIOMotorDatabase, collection: str):
        self.collection = db[collection]

    async def insert(self, data: dict) -> dict:
        data = {**data, "created_at": data.get("created_at", now_utc()), "updated_at": now_utc()}
        result = await self.collection.insert_one(data)
        return serialize(await self.collection.find_one({"_id": result.inserted_id}))

    async def find_one(self, query: dict) -> dict | None:
        if "id" in query:
            query = {**query, "_id": ObjectId(query.pop("id"))}
        return serialize(await self.collection.find_one(query))

    async def find_many(self, query: dict | None = None, limit: int = 100, sort: list[tuple[str, int]] | None = None) -> list[dict]:
        cursor = self.collection.find(query or {})
        if sort:
            cursor = cursor.sort(sort)
        return [serialize(item) async for item in cursor.limit(limit)]

    async def upsert_one(self, query: dict, update: dict) -> dict:
        update = {**update, "updated_at": now_utc()}
        await self.collection.update_one(query, {"$set": update, "$setOnInsert": {"created_at": now_utc()}}, upsert=True)
        return serialize(await self.collection.find_one(query))
