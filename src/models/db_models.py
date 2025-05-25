from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class History(Base):
    __tablename__ = 'chat_history'
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    history = Column(Text, nullable=False)
    created_on = Column(DateTime, server_default=func.now())
