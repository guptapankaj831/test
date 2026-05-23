from __future__ import annotations

import logging

from langchain_community.tools import DuckDuckGoSearchResults
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

logger = logging.getLogger(__name__)

_search_tool = DuckDuckGoSearchResults(
    output_format="list", num_results=settings.duckduckgo_num_results
)


@retry(
    reraise=True,
    stop=stop_after_attempt(settings.web_search_max_retries),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
)
def _search_with_retry(query: str) -> list[dict]:
    return _search_tool.invoke(query)


def web_search(query: str) -> list[dict]:
    """Run a DuckDuckGo search with retry/backoff.

    Returns a list of `{snippet, title, link, date}` dicts, or `[]` if every
    retry failed (rate limit, transient network). Never raises — the caller
    treats an empty list the same as "no results", which keeps the agent loop
    resilient to flaky web search.
    """
    try:
        results = _search_with_retry(query)
        logger.info("web_search ok query=%r results=%d", query, len(results))
        return results
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("web_search failed query=%r error=%s", query, exc)
        return []
