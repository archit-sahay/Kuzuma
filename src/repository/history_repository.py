from src.models.db_models import History  # your Pydantic model for MongoDB


async def add_history(db, name: str, email: str, history: str):
    history_doc = History(name=name, email=email, history=history)
    result = await db.chat_history.insert_one(history_doc.dict())
    return str(result.inserted_id)
