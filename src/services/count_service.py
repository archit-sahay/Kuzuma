from src.config.db_config import get_db
from src.logger import get_logger

log = get_logger(__name__)


async def count_service():
    async with get_db() as db:
        visitor_count = len(await db.chat_history.distinct("email"))
    log.info(f"No. of visitors yet: [{visitor_count}]")
    return visitor_count
