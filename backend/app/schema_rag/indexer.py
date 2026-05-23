"""ChromaDB schema index — auto-describes each table and serves top-K retrieval for the SQL generator."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection

from app.config import settings
from app.llm import get_embeddings
from app.schema_rag.describer import TableDescription, describe_table
from app.schema_rag.introspect import TableInfo, introspect_database

logger = logging.getLogger(__name__)

_collection: Collection | None = None


def _get_collection() -> Collection:
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        _collection = client.get_or_create_collection(
            name=settings.chroma_collection_name,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _table_hash(table: TableInfo) -> str:
    # Sample rows are deliberately excluded — they shift between runs and would
    # invalidate the cache even when the schema itself hasn't moved.
    payload = {
        "columns": [c.model_dump() for c in table.columns],
        "foreign_keys": [fk.model_dump() for fk in table.foreign_keys],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _build_documents(
    table: TableInfo, desc: TableDescription, table_hash: str
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = [
        {
            "id": f"table::{table.name}",
            "text": desc.table_description,
            "metadata": {"kind": "table", "table": table.name, "table_hash": table_hash},
        }
    ]
    col_desc_by_name = {cd.column_name: cd.description for cd in desc.column_descriptions}
    for col in table.columns:
        text = col_desc_by_name.get(col.column_name, "").strip()
        if not text:
            continue
        docs.append(
            {
                "id": f"column::{table.name}::{col.column_name}",
                "text": text,
                "metadata": {
                    "kind": "column",
                    "table": table.name,
                    "column": col.column_name,
                    "table_hash": table_hash,
                },
            }
        )
    return docs


def _upsert(collection: Collection, docs: list[dict[str, Any]]) -> None:
    if not docs:
        return
    print(f"\ndocs: {docs}\n")
    texts = [d["text"] for d in docs]
    print(f"\ntexts: {texts}\n")
    vectors = get_embeddings().embed_documents(texts)
    collection.upsert(
        ids=[d["id"] for d in docs],
        documents=texts,
        embeddings=vectors,
        metadatas=[d["metadata"] for d in docs],
    )


def ensure_index() -> None:
    """Build or refresh the schema index. Idempotent — unchanged tables aren't re-described."""
    collection = _get_collection()
    existing = collection.get(include=["metadatas"])
    existing_hashes: dict[str, str] = {}
    print(f"Pre Filter existing_hashes : {existing_hashes}")
    for meta in existing["metadatas"] or []:
        if meta and meta.get("kind") == "table":
            existing_hashes[meta["table"]] = meta.get("table_hash", "")

    print(f"existing_hashes : {existing_hashes}")

    tables = introspect_database()
    current_ids: set[str] = set()
    described = 0

    for table in tables:
        h = _table_hash(table)
        current_ids.add(f"table::{table.name}")
        for col in table.columns:
            current_ids.add(f"column::{table.name}::{col.column_name}")

        if existing_hashes.get(table.name) == h:
            continue

        desc = describe_table(table)
        print(f"\ndescribe_table_result: {desc}\n")
        _upsert(collection, _build_documents(table, desc, h))
        described += 1

    stale_ids = set(existing["ids"]) - current_ids
    if stale_ids:
        collection.delete(ids=list(stale_ids))

    logger.info(
        "ensure_index: %d table(s), %d re-described, %d stale doc(s) removed",
        len(tables),
        described,
        len(stale_ids),
    )


def retrieve(question: str, k: int | None = None) -> list[dict[str, Any]]:
    """Embed the question and return top-K schema docs (`id`, `text`, `metadata`, `distance`)."""
    top_k = k if k is not None else settings.retrieval_top_k
    vector = get_embeddings().embed_query(question)
    result = _get_collection().query(
        query_embeddings=[vector],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    return [
        {"id": doc_id, "text": text, "metadata": meta, "distance": dist}
        for doc_id, text, meta, dist in zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        )
    ]
