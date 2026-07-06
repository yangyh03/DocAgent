from openai import OpenAI
from langchain_openai import ChatOpenAI

from app.config import settings


def create_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        model_name=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.model_timeout_seconds,
        max_retries=settings.model_retry_times,
    )


def create_embedding_client() -> OpenAI:
    return OpenAI(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        timeout=settings.model_timeout_seconds,
        max_retries=settings.model_retry_times,
    )
