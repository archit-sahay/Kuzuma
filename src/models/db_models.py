from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
from bson import ObjectId
# from pydantic import core_schema


class PyObjectId(ObjectId):

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    def __get_pydantic_json_schema__(self, core_schema):
        # Tell Pydantic this should be serialized as a string
        return core_schema.StringSchema()


# Pydantic model for request/response
class History(BaseModel):
    # id: Optional[PyObjectId] = Field(default=None, alias="_id")
    email: EmailStr
    name: str
    messages: list = Field(default_factory=list)  # list of {role, content, timestamp}
    created_on: Optional[datetime] = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
