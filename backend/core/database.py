from datetime import datetime

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
)

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

DATABASE_URL = 'postgresql://postgres:12345@localhost:5432/Helix'

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    role = Column(String(50), default="user")
    created_at = Column(DateTime, default=datetime.utcnow)

    chats = relationship("ChatHistory", back_populates="user")
    memories = relationship("Memory", back_populates="user")

class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    user_message = Column(Text, nullable=False)
    ai_response = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="chats")

class Memory(Base):
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    owner_type = Column(String(50), default="user")
    category = Column(String(100), default="general")
    content = Column(Text, nullable=False)
    importance = Column(Integer, default=3)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="memories")

def get_or_create_user(db, name: str):
    clean_name = name.strip().lower()

    user = db.query(User).filter(User.name == clean_name).first()

    if user:
        return user
    
    user = User(name=clean_name)
    db.add(user)
    db.commit()
    db.refresh(user)

    return user

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
        print(f"Banco indosponível: {exc}")
        return False