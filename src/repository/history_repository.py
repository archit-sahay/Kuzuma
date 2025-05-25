from sqlalchemy.orm import Session

from src.models.db_models import History


def add_history(db: Session, name: str, email: str, history: str):
    db.add(History(name=name, email=email, history=history))
    db.commit()
