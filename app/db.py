import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if not url:
        url = "sqlite:///./stefanos_garage.db"
    return url

DATABASE_URL = _db_url()

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
from sqlalchemy import text

def ensure_schema(engine):
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE visit_checklist_lines ADD COLUMN parts_code VARCHAR"))
        except Exception:
            pass

        try:
            conn.execute(text("ALTER TABLE visit_checklist_lines ADD COLUMN parts_qty INTEGER DEFAULT 0"))
        except Exception:
            pass

        conn.commit()

ensure_schema(engine)
