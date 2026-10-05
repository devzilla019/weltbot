import os
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./weltbot.db")

# Fix relative path for cloud environments
if DATABASE_URL.startswith("sqlite:///./"):
    db_path = os.path.join(os.path.dirname(__file__), "weltbot.db")
    DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_light_migrations():
    """
    Add columns introduced after the initial schema, without a full
    migration tool. Safe to call on every startup (idempotent).
    """
    wanted = {
        "crt_levels": [("timeframe", "VARCHAR DEFAULT '1d'")],
        "forex_trades": [
            ("crt_timeframe", "VARCHAR"),
            ("confirm_timeframe", "VARCHAR"),
            ("entry_timeframe", "VARCHAR"),
            ("poi", "VARCHAR"),
        ],
    }
    try:
        insp = inspect(engine)
        existing_tables = set(insp.get_table_names())
        with engine.begin() as conn:
            for table, columns in wanted.items():
                if table not in existing_tables:
                    continue
                have = {c["name"] for c in insp.get_columns(table)}
                for col_name, col_def in columns:
                    if col_name not in have:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"))
                        print(f"[db] migrated: added {table}.{col_name}")
    except Exception as e:
        print(f"[db] migration warning: {e}")