import os
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.db_models import Base

load_dotenv()

URL = os.getenv("DB_URL")

engine = create_engine(
    URL,
    echo=True,
    pool_size=20,
    max_overflow=30,
    pool_timeout=30,
    pool_recycle=1800
)
engine.dispose()
Session_Local = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables():
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db():
    db = Session_Local()
    try:
        yield db
    finally:
        db.close()
