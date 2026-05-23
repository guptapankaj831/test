"""NL-to-SQL Analyst — Streamlit frontend.

Submits a question to the backend's `/ask` SSE endpoint, parses semantic event frames,
and drives three tabs: SQL, Result, Summary. `schema` events are consumed but not rendered.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterator

import httpx
import pandas as pd
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="NL-to-SQL Analyst", layout="wide")
st.title("NL-to-SQL Analyst")
st.caption("Natural-language question → safe SQL → tabular result + streamed summary.")

with st.form("ask_form", clear_on_submit=False):
    question = st.text_input("Question", placeholder="Top 5 customers by total payments.")
    submitted = st.form_submit_button("Ask")


def _stream_events(question: str) -> Iterator[tuple[str, Any]]:
    """Parse SSE frames from the backend into (event_name, json_payload) tuples."""
    timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
    with httpx.Client(timeout=timeout) as client:
        with client.stream(
            "POST",
            f"{BACKEND_URL}/ask",
            json={"question": question},
            headers={"Accept": "text/event-stream"},
        ) as resp:
            resp.raise_for_status()
            event_name: str | None = None
            data_buf: list[str] = []
            for line in resp.iter_lines():
                if line == "":
                    if event_name is not None:
                        yield event_name, json.loads("\n".join(data_buf))
                    event_name, data_buf = None, []
                elif line.startswith("event: "):
                    event_name = line[len("event: "):]
                elif line.startswith("data: "):
                    data_buf.append(line[len("data: "):])


if submitted and question.strip():
    tab_summary, tab_result, tab_sql = st.tabs(["Summary", "Result", "SQL"])
    sql_box = tab_sql.empty()
    result_box = tab_result.empty()
    summary_box = tab_summary.empty()
    summary_tokens: list[str] = []
    pending_sql = None

    try:
        for event, data in _stream_events(question.strip()):
            if event == "sql":
                pending_sql = data
            elif event == "result":
                with result_box.container():
                    rows = data["rows"]
                    columns = data["columns"]
                    n = len(rows)
                    suffix = " (capped — more rows exist)" if data["truncated"] else ""
                    st.caption(f"{n} row(s){suffix}")

                    if n > 0:
                        if pending_sql is not None:
                            with sql_box.container():
                                st.code(pending_sql["sql"], language="sql")

                        @st.fragment
                        def _table_view():
                            page_size = st.session_state.get("page_size", 10)
                            pages = max(1, (n + page_size - 1) // page_size)
                            current_page = min(st.session_state.get("result_page", 1), pages)
                            start = (current_page - 1) * page_size

                            st.dataframe(
                                pd.DataFrame(rows[start:start + page_size], columns=columns),
                                width="stretch", hide_index=True,
                            )

                            b1, b2, b3 = st.columns([2, 1, 1])
                            with b1:
                                st.markdown(f"\n**Page {current_page} of {pages}**")
                            with b2:
                                st.number_input(
                                    "Page", min_value=1, max_value=pages, value=current_page,
                                    step=1, key="result_page",
                                )
                            with b3:
                                st.selectbox(
                                    "Page Size", [10, 25, 50, 100], index=0, key="page_size"
                                )
                        _table_view()
            elif event == "summary":
                summary_tokens.append(data)
                summary_box.markdown("".join(summary_tokens))
            # elif event == "done":
            #     st.success(
            #         f"Done in {data['elapsed_s']}s "
            #         f"(retries — validation: {data['validation_retries']}, "
            #         f"execution: {data['execution_retries']})"
            #     )
            elif event == "error":
                msg = f"Failed at stage `{data['stage']}`: {data['message']}"
                if data.get("sql"):
                    msg += f"\n\n```sql\n{data['sql']}\n```"
                st.error(msg)
                break
    except httpx.HTTPError as e:
        st.error(f"Backend request failed: {e}")
