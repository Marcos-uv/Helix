from datetime import datetime

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker, relationship


DATABASE_URL = "postgresql://postgres:12345@localhost:5432/Helix"


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), unique=True, index=True, nullable=False)
    role = Column(String(50), default="user")

    created_at = Column(DateTime, default=datetime.utcnow)

    chats = relationship(
        "ChatHistory",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    memories = relationship(
        "Memory",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    user_message = Column(Text, nullable=False)
    ai_response = Column(Text, nullable=False)

    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship(
        "User",
        back_populates="chats",
    )


Index(
    "idx_chat_history_user_timestamp",
    ChatHistory.user_id,
    ChatHistory.timestamp,
)


class Memory(Base):
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    owner_type = Column(String(50), default="user", index=True)
    # user, project, system

    category = Column(String(100), default="general", index=True)
    # general, technical_decision, preference, system_rule, project_goal

    content = Column(Text, nullable=False)

    importance = Column(Integer, default=3, index=True)
    # 1 = baixa
    # 3 = normal
    # 5 = muito importante

    source = Column(String(100), default="chat")
    # chat, manual, obsidian, system_scan, diagnostic

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    last_used_at = Column(DateTime, nullable=True)

    user = relationship(
        "User",
        back_populates="memories",
    )


Index(
    "idx_memories_user_category",
    Memory.user_id,
    Memory.category,
)

Index(
    "idx_memories_owner_importance",
    Memory.owner_type,
    Memory.importance,
)


def get_or_create_user(db, name: str):
    clean_name = name.strip().lower()

    user = db.query(User).filter(User.name == clean_name).first()

    if user:
        return user

    try:
        user = User(name=clean_name)

        db.add(user)
        db.commit()
        db.refresh(user)

        return user

    except SQLAlchemyError as exc:
        db.rollback()
        print(f"Erro ao criar usuário: {exc}")
        raise


def get_db():
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


def init_db() -> bool:
    try:
        Base.metadata.create_all(bind=engine)
        return True

    except SQLAlchemyError as exc:
        print(f"Banco indisponível: {exc}")
        return False