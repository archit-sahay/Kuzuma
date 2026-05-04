from src.models.db_models import History  # your Pydantic model for MongoDB


async def add_history(db, name: str, email: str, messages: list, conversation_id: str = None, tool_calls: list = None, client_ip: str = None):
    history_doc = History(name=name, email=email, messages=messages, conversation_id=conversation_id, tool_calls=tool_calls or [], client_ip=client_ip)
    result = await db.chat_history.insert_one(history_doc.model_dump())
    return str(result.inserted_id)
