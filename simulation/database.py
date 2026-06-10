# database.py
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
import os

from schema_config import DB_SCHEMA


def _load_env_dotfiles():
    """Populate os.environ from FAB_BEAR/.env then repo-root .env (setdefault only)."""
    here = Path(__file__).resolve().parent
    for env_path in (here.parent / ".env", here.parent.parent / ".env"):
        if not env_path.is_file():
            continue
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key:
                    os.environ.setdefault(key, val)
        except OSError:
            continue


_load_env_dotfiles()

# Import after env load so models pick up POSTGRES_SCHEMA via schema_config.
from models import Base  # noqa: E402

# ---------------------------------------------------------
# [설정] DB 주소 입력 (PostgreSQL)
# ---------------------------------------------------------
default_url = "postgresql://postgres:postgres@localhost:5432/postgres"
if os.getenv("POSTGRES_USER") and os.getenv("POSTGRES_PASSWORD") and os.getenv("POSTGRES_DB"):
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    db_name = os.getenv("POSTGRES_DB")
    default_url = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

_explicit_url = os.getenv("DATABASE_URL")
# Host-side runs: FAB_BEAR POSTGRES_* (localhost:5433) beats repo-root DATABASE_URL=@db:5432.
if _explicit_url and "@db:" in _explicit_url and os.getenv("POSTGRES_HOST", "localhost") not in ("", "db"):
    DATABASE_URL = default_url
elif _explicit_url:
    DATABASE_URL = _explicit_url
else:
    DATABASE_URL = default_url

# 1. 엔진(Engine) 시동: DB와 연결하는 본체
engine = create_engine(DATABASE_URL)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_conn, _connection_record):
    """Route ORM/raw SQL to simulation schema (fallback public for extensions)."""
    if not DB_SCHEMA or DB_SCHEMA == "public":
        return
    cursor = dbapi_conn.cursor()
    cursor.execute(f"SET search_path TO {DB_SCHEMA}, public")
    cursor.close()


# 2. 세션(Session) 생성기: 실제로 데이터를 넣고 뺄 때 쓰는 '작업 창구'
# expire_on_commit=False: FabEnv keeps ORM master rows after commit (PM/BD SimPy processes).
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


def ensure_schema(conn) -> None:
    """CREATE SCHEMA IF NOT EXISTS + search_path for migration batches."""
    if not DB_SCHEMA or DB_SCHEMA == "public":
        return
    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}"))
    conn.execute(text(f"SET search_path TO {DB_SCHEMA}, public"))


# 3. 테이블 생성 함수 (이걸 실행하면 DB에 빈 테이블들이 쫘악 생깁니다!)
def create_tables():
    """Create any missing tables in POSTGRES_SCHEMA. Safe to re-run on existing DBs."""
    with engine.begin() as conn:
        ensure_schema(conn)
    Base.metadata.create_all(bind=engine)
    print(f"✅ 데이터베이스 테이블 생성 완료! (schema={DB_SCHEMA})")
