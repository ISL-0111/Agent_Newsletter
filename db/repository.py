"""
PostgreSQL + pgvector 연동
- summaries 테이블: 요약 이력 저장
- 벡터 컬럼으로 의미 검색 지원
"""
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Float
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import select, text
from pgvector.sqlalchemy import Vector
from config.settings import settings
from email.utils import parsedate_to_datetime

Base = declarative_base()
engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Summary(Base):
    __tablename__ = "summaries"

    id          = Column(String, primary_key=True)   # message_id
    source      = Column(String, index=True)          # McKinsey, Substack 등
    subject     = Column(Text)
    importance  = Column(String)
    summary     = Column(Text)
    received_at = Column(DateTime)
    created_at  = Column(DateTime, default=datetime.utcnow)
    embedding   = Column(Vector(768))               # Vertex AI text-embedding-004 차원수


class UserPreference(Base):
    __tablename__ = "user_preferences"

    key   = Column(String, primary_key=True)   # "skip_list", "source_settings" 등
    value = Column(Text)                        # JSON 직렬화


async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


async def save_summary(data: dict):
    async with AsyncSessionLocal() as session:
        summary = Summary(
            id=data["message_id"],
            source=data["source"],
            subject=data["subject"],
            importance=data["importance"],
            summary=data["summary"],
            received_at=_parse_date(data["received_at"]),
            embedding=data.get("embedding"),
        )
        await session.merge(summary)   # ← await 추가
        await session.commit()


async def search_similar(query_vector: list[float], top_k: int = 5) -> list[dict]:
    """pgvector 코사인 유사도 검색"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Summary)
            .order_by(Summary.embedding.cosine_distance(query_vector))
            .limit(top_k)
        )
        rows = result.scalars().all()
        return [
            {
                "source": r.source,
                "subject": r.subject,
                "summary": r.summary,
                "received_at": r.received_at.isoformat(),
                "importance": r.importance,
            }
            for r in rows
        ]


async def get_skip_list() -> list[str]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserPreference).where(UserPreference.key == "skip_list")
        )
        row = result.scalar_one_or_none()
        if not row:
            return []
        import json
        return json.loads(row.value)

def _parse_date(date_str: str) -> datetime:
    """Gmail RFC 2822 형식과 ISO 형식 모두 처리"""
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        try:
            return parsedate_to_datetime(date_str).replace(tzinfo=None)
        except Exception:
            return datetime.utcnow()