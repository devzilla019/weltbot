import os
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./weltbot.db")

# Railway/Heroku hand out postgres:// URLs, which SQLAlchemy 2.x rejects.
# Normalise the scheme so the Postgres driver is picked up correctly.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# Fix relative path for cloud environments
if DATABASE_URL.startswith("sqlite:///./"):
    db_path = os.path.join(os.path.dirname(__file__), "weltbot.db")
    DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    pool_pre_ping=True,
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

    Column types are chosen per dialect — SQLite accepts the generic
    VARCHAR/FLOAT/BOOLEAN spellings, Postgres needs the boolean literal
    written as FALSE rather than 0.
    """
    is_postgres = engine.dialect.name == "postgresql"
    bool_default = "FALSE" if is_postgres else "0"
    varchar = "VARCHAR(64)" if is_postgres else "VARCHAR"

    wanted = {
        "crt_levels": [("timeframe", f"{varchar} DEFAULT '1d'")],
        "forex_trades": [
            ("crt_timeframe", varchar),
            ("confirm_timeframe", varchar),
            ("entry_timeframe", varchar),
            ("poi", varchar),
            # Refined CRT with Pullback Entry — partial take-profit tracking
            ("tp1", "FLOAT"),
            ("tp2", "FLOAT"),
            ("entry_type", varchar),
            ("partial_tp_hit", f"BOOLEAN DEFAULT {bool_default}"),
        ],
    }
    try:
        insp = inspect(engine)
        existing_tables = set(insp.get_table_names())
        with engine.begin() as conn:
            for table, columns in wanted.items():
                if table not in existing_tables:
                    continue
                have = {c["name"] for c in inspect(engine).get_columns(table)}
                for col_name, col_def in columns:
                    if col_name not in have:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"))
                        print(f"[db] migrated: added {table}.{col_name}")
    except Exception as e:
        print(f"[db] migration warning: {e}")