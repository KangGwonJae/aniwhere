"""서비스용 DB(PostgreSQL + pgvector) 연결. 수집 DB가 아니라 migrate로 옮긴 DB를 읽습니다."""
import psycopg
from psycopg.rows import dict_row

from aniwhere.config import service_db_url


def connect():
    return psycopg.connect(service_db_url(), row_factory=dict_row, autocommit=True)
