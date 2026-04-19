from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Optional
from datetime import datetime, timezone
from bson import ObjectId


class PyObjectId(ObjectId):

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @staticmethod
    def __get_pydantic_json_schema__(schema, handler):
        return handler(schema)


# Pydantic model for request/response
class History(BaseModel):
    # id: Optional[PyObjectId] = Field(default=None, alias="_id")
    conversation_id: Optional[str] = None
    email: EmailStr
    name: str
    messages: list = Field(default_factory=list)  # list of {role, content, timestamp}
    tool_calls: list = Field(default_factory=list)  # list of {name, args, timestamp}
    created_on: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str},
    )
