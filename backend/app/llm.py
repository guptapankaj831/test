"""OpenAI client factories for chat and embeddings."""

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import settings


def get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        temperature=settings.openai_temperature
    )


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model
    )
