import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Σε Render, κράτα sqlite σε disk (persistent) αν έχεις disk
# Αν δεν έχεις disk, θα είναι προσωρινό αλλά θα δουλεύει.
DB_URL = os.getenv("DATABASE_URL", "").strip()

if DB_URL:
    # Render sometimes gives postgres URLs starting with postgres://
    if DB_URL.startswith("postgres://"):
        DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)
    connect_args = {}
else:
    # local sqlite file
    DB_URL = "sqlite:///./stefanos.db"
    connect_args = {"check_same_thread": False}

engine = create_engine(DB_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
