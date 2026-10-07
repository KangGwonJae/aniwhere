"""설정 읽기: 비밀 값은 .env, 바뀔 수 있는 값은 config/settings.yaml."""
import os
import re
from functools import lru_cache
from pathlib import Path

import psycopg.conninfo
import yaml

REPO = Path(__file__).resolve().parents[1]


def _load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m and not line.lstrip().startswith("#") and m.group(2):
            os.environ.setdefault(m.group(1), m.group(2).strip("\"'"))


_load_env(REPO / ".env")


@lru_cache
def settings() -> dict:
    return yaml.safe_load((REPO / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}


def section(name: str) -> dict:
    return settings().get(name) or {}


def service_db_url() -> str:
    """앱이 읽는 DB 주소. DATABASE_URL에서 DB 이름만 서비스용(config의 service_db.name)으로 바꿉니다.

    다른 DB를 쓰려면 ANIWHERE_DB_URL에 주소를 통째로 넣습니다(테스트가 이렇게 씁니다).
    """
    if os.environ.get("ANIWHERE_DB_URL"):
        return os.environ["ANIWHERE_DB_URL"]
    url = os.environ.get("DATABASE_URL", "postgresql:///aniwhere")
    name = section("service_db").get("name")
    return psycopg.conninfo.make_conninfo(url, dbname=name) if name else url


def openai_api_key() -> str | None:
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY") or None
