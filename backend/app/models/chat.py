from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy import event
from sqlalchemy.orm import Session as SASession
from sqlalchemy.sql import func
from core.database import Base

class Chat(Base):
    __tablename__ = "chats"
    
    id = Column(String, primary_key=True, index=True)
    title = Column(String, index=True)
    owner_id = Column(String, ForeignKey("auth.users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    __table_args__ = { 'schema': 'auth' }
    # Only map the id column for the provider-managed auth.users table.
    # Do NOT map provider-specific columns (email/name/etc.) because
    # different providers may have different schemas and selecting
    # non-existent columns leads to UndefinedColumn errors. We only need
    # the id here to validate existence and create foreign keys.
    id = Column(String, primary_key=True, index=True)
    # Map a small, safe subset of additional read-only columns that
    # are commonly present in Supabase-managed auth.users. These are
    # used for logging/display only; the ORM listener prevents writes.
    email = Column(String, unique=False, index=True, nullable=True)
    raw_user_meta_data = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)


class File(Base):
    __tablename__ = "files"
    id = Column(String, primary_key=True, index=True)
    chat_id = Column(String, ForeignKey("chats.id"), nullable=True)
    message_id = Column(String, ForeignKey("messages.id"), nullable=True, index=True)
    owner_id = Column(String, ForeignKey("auth.users.id"), nullable=True)
    name = Column(String, nullable=False)
    size = Column(String, nullable=True)
    type = Column(String, nullable=True)
    download_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(String, primary_key=True, index=True)
    chat_id = Column(String, ForeignKey("chats.id"), nullable=False)
    role = Column(String, nullable=False)  # 'user' или 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    chat = relationship("Chat", back_populates="messages")


# Enforce read-only constraint for auth.users at the ORM level.
# This prevents accidental INSERT/UPDATE/DELETE on the User model via SQLAlchemy.
@event.listens_for(SASession, "before_flush")
def _prevent_auth_user_writes(session, flush_context, instances):
    # Gather all instances that will be flushed
    to_check = set(session.new) | set(session.dirty) | set(session.deleted)
    for inst in to_check:
        try:
            if isinstance(inst, User):
                raise RuntimeError("Attempt to modify auth.users via ORM detected; auth.users is read-only.")
        except Exception:
            # If User is not fully mapped or any other error occurs, raise to be safe
            raise
