# database.py
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base
import os


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

# ---------------------------------------------------------
# [설정] DB 주소 입력 (PostgreSQL)
# 도커로 띄운 경우 보통: postgresql://유저명:비번@localhost:포트/DB명
# ---------------------------------------------------------
# Docker Compose / 로컬 실행 공용:
# - 환경변수 DATABASE_URL 이 있으면 우선 사용
# - 없으면 POSTGRES_* 환경변수로 URL을 조합
# - 그것도 없으면 로컬 기본값 사용
default_url = "postgresql://postgres:postgres@localhost:5432/postgres"
if os.getenv("POSTGRES_USER") and os.getenv("POSTGRES_PASSWORD") and os.getenv("POSTGRES_DB"):
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    db_name = os.getenv("POSTGRES_DB")
    default_url = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

DATABASE_URL = os.getenv("DATABASE_URL", default_url)

# 1. 엔진(Engine) 시동: DB와 연결하는 본체
engine = create_engine(DATABASE_URL)

# 2. 세션(Session) 생성기: 실제로 데이터를 넣고 뺄 때 쓰는 '작업 창구'
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 3. 테이블 생성 함수 (이걸 실행하면 DB에 빈 테이블들이 쫘악 생깁니다!)
def create_tables():
    Base.metadata.create_all(bind=engine)
    print("✅ 데이터베이스 테이블 생성 완료!")