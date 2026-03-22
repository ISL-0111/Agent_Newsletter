"""
LLM 팩토리
- 모든 LLM 호출은 이 모듈을 통해 생성
- Vertex AI 경유 Gemini 2.5 사용
- 노드별 모델 티어 분리 (Flash: 분류·파싱 / Pro: 요약·Vision)
"""
from functools import lru_cache
from langchain_google_vertexai import ChatVertexAI, VertexAIEmbeddings
from config.settings import settings


@lru_cache(maxsize=1)
def get_flash_llm() -> ChatVertexAI:
    return ChatVertexAI(
        model_name=settings.gemini_flash_model,  # gemini-2.5-flash
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        temperature=0,
        max_tokens=1024,
    )

@lru_cache(maxsize=1)
def get_pro_llm() -> ChatVertexAI:
    return ChatVertexAI(
        model_name=settings.gemini_pro_model,    # gemini-2.5-pro
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        temperature=0.3,
        max_tokens=4096,
    )


@lru_cache(maxsize=1)
def get_embeddings() -> VertexAIEmbeddings:
    """Vertex AI 임베딩 — OpenAI 대신 GCP 크레딧 사용"""
    return VertexAIEmbeddings(
        model_name="text-embedding-004",
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
    )
