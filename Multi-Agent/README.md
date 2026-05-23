# Multi-Agent Research Assistant

A LangGraph-powered research assistant that orchestrates four specialized agents — **Planner**, **Researcher**, **Critic**, and **Writer** — to investigate a topic and produce a cited Markdown report.

## What it does

- Breaks a vague research question into a structured plan
- Runs web searches (DuckDuckGo, no API key) and collects evidence-backed findings
- Drafts a report, critiques it, and iterates until the quality bar is met
- Streams progress to a Streamlit UI over SSE

## Architecture

```
+--------------------+         +-------------------------+
|  Streamlit UI      | <-SSE-> |  FastAPI Backend        |
+--------------------+         +-----------+-------------+
                                           |
                                           v
                              +------------+------------+
                              |  LangGraph State Machine|
                              |                         |
                              |   Planner -> Researcher |
                              |       ^         |       |
                              |       |         v       |
                              |    Writer <-- Critic    |
                              +-------------------------+
```

## Tech stack

- **Orchestration:** LangGraph (state, reducers, conditional edges, async streaming)
- **LLM:** OpenAI GPT-4o via `with_structured_output` + Pydantic v2
- **Web search:** DuckDuckGo with `tenacity` retry/backoff
- **Backend:** FastAPI with `text/event-stream`
- **Frontend:** Streamlit

## Sample questions

- Compare Snowflake vs Databricks for a 2026 data warehouse.
- What are the leading open-source vector databases in 2026, and how do they differ?
- Summarize the current state of AI agent frameworks (LangGraph, CrewAI, AutoGen).
- Evaluate Next.js vs Remix for a new e-commerce frontend.
- What are recent published migration stories from MongoDB to Postgres?

## How to run

```bash
# 1. Configure
cp .env.example .env
# Edit .env and set OPENAI_API_KEY

# 2. Install
uv venv
uv pip install -r requirements.txt

# 3. Backend (terminal 1)
cd backend
uvicorn app.main:app --reload

# 4. Frontend (terminal 2)
streamlit run frontend/app.py
```

Open <http://localhost:8501>.
