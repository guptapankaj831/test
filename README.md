# Natural-Language-to-SQL Analyst

A FastAPI + LangChain + Streamlit app that turns plain-English business questions into safe, read-only SQL against a MySQL database — and streams a natural-language summary alongside the result table.

Sample database: **Sakila** (MySQL's DVD-rental dataset, 16 tables).

## Run

```bash
cp .env.example .env       # then set OPENAI_API_KEY and MYSQL_*_PASSWORD
docker compose up --build
```

- Streamlit UI: http://localhost:8501
- FastAPI backend: http://localhost:8000 (`/docs` for OpenAPI)

On first start, the backend describes each Sakila table with the LLM and embeds the descriptions into ChromaDB (~30s). Restart is instant — the index is hash-cached.

## Try

- *"Top 5 customers by total payments."*
- *"Which film categories generated the most revenue?"*
- *"Films that have never been rented."*

## How it's safe

Three independent layers — a hallucinated `DROP TABLE` has to defeat all three:

1. **DB role** — the MySQL user is granted only `SELECT`. No `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `GRANT`.
2. **AST validation** — `sqlglot` parses the SQL with `dialect="mysql"`; rejects anything that isn't a single SELECT (no DML, no DDL, no `INTO OUTFILE`, no statement chaining).
3. **Execution caps** — per-connection `MAX_EXECUTION_TIME` plus an auto-applied `LIMIT 1000` if the query doesn't already cap.

## Pipeline

```
question → retrieve schema slice (Chroma) → generate SQL (LLM) → validate AST
                                                                    ↓
                                  retry on validation / execution failure
                                                                    ↓
   execute (LIMIT-clamped) → stream natural-language summary → done
```

Every stage emits a semantic SSE event (`schema`, `sql`, `result`, `summary`, `done`, `error`) that the Streamlit UI consumes.

## Tech stack

| Layer | Choice |
|-------|--------|
| Orchestration | LangChain `RunnableSequence` for the structured SQL plan; async generator for the outer pipeline |
| LLM | OpenAI GPT-4o |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector store | ChromaDB (persistent, in-process) |
| Database | MySQL 8 (Sakila) |
| Driver | SQLAlchemy + `pymysql` |
| SQL validation | `sqlglot` |
| Backend | FastAPI + native `StreamingResponse` for SSE |
| Frontend | Streamlit |
| Config | pydantic-settings |

## Folder layout

```
NL-to-SQL-Analyst/
├── backend/
│   ├── app/
│   │   ├── main.py            # POST /ask (SSE), GET /health
│   │   ├── chain.py           # retrieve → generate → validate → execute → summarize
│   │   ├── summarizer.py      # streaming LLM summary
│   │   ├── sql/
│   │   │   ├── validator.py   # sqlglot AST check
│   │   │   └── executor.py    # safe execute with LIMIT clamp
│   │   ├── schema_rag/        # introspect + describe + Chroma index
│   │   ├── schemas/ask.py     # pydantic request/plan models
│   │   ├── prompts/           # describer.md, sql_generator.md, summarizer.md
│   │   ├── config.py          # pydantic-settings
│   │   ├── db.py              # read-only SQLAlchemy engine
│   │   └── llm.py             # OpenAI client factories
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── app.py                 # Streamlit form + tabbed result
│   ├── requirements.txt
│   └── Dockerfile
├── db/init/                   # SQL scripts the mysql container runs on first boot
├── sakila-db/                 # raw Sakila schema + data (sources for db/init)
├── docker-compose.yml
├── .env.example
└── README.md
```
