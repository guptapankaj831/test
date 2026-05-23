from langchain_openai import ChatOpenAI

from app.config import settings

llm = ChatOpenAI(
    model=settings.openai_model,
    temperature=settings.openai_temperature,
    api_key=settings.openai_api_key,
)
