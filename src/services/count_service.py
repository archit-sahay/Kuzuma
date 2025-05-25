from src.config.db_config import get_db
from sqlalchemy.sql import func
from src.models.db_models import History


def count_service():
    with get_db() as db:
        visitor_count = db.query(func.count(func.distinct(History.email))).scalar()
    print(f"No. of visitors yet: [{visitor_count}]")
    return visitor_count
