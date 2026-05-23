import json
import os

import httpx
import streamlit as st

API_URL = os.environ.get("MARA_API_URL", "http://127.0.0.1:8000")
RESEARCH_ENDPOINT = f"{API_URL}/research"

st.set_page_config(page_title="Multi-Agent Research Assistant", layout="wide")
st.title("Multi-Agent Research Assistant")


with st.sidebar:
    st.header("Settings")
    max_iterations = st.slider("Max critic iterations", min_value=1, max_value=5, value=3)
    request_timeout = st.number_input(
        "Request timeout (s)", min_value=60, max_value=600, value=300, step=30
    )


with st.form("research_form", clear_on_submit=False):
    query = st.text_area(
        "Research question",
        placeholder="e.g. Compare Snowflake vs Databricks for 2026 data warehouse adoption",
        height=100,
    )
    submitted = st.form_submit_button("Run research")


def _iter_sse(response: httpx.Response):
    event_name: str | None = None
    data_lines: list[str] = []
    for line in response.iter_lines():
        if line == "":
            if event_name and data_lines:
                try:
                    yield event_name, json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    pass
            event_name = None
            data_lines = []
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())


def _new_result() -> dict:
    return {
        "plan": None,
        "findings": [],
        "critiques": [],
        "draft": "",
        "iteration": 0,
        "total_findings": 0,
        "done": False,
    }


def _stream_run(query: str, max_iter: int, timeout: int) -> dict | None:
    payload = {"query": query, "max_iterations": max_iter}
    result = _new_result()

    status = st.status(
        "Running planner → researcher → writer → critic loop ...", expanded=True
    )
    with status:
        log_placeholder = st.empty()
        log_lines: list[str] = []

        def push(line: str) -> None:
            log_lines.append(line)
            log_placeholder.markdown("\n\n".join(log_lines))

        try:
            with httpx.stream(
                "POST", RESEARCH_ENDPOINT, json=payload, timeout=timeout
            ) as r:
                if r.status_code != 200:
                    st.error(f"Backend returned HTTP {r.status_code}")
                    return None

                for event_name, data in _iter_sse(r):
                    if event_name == "plan":
                        result["plan"] = data
                        push(
                            f"📋 **Plan ready** — {data['objective']} "
                            f"({len(data['sub_questions'])} sub-questions)"
                        )

                    elif event_name == "research_progress":
                        result["findings"].extend(data["new_findings"])
                        result["total_findings"] = data["total_findings"]
                        mode = "gap-driven" if data["gap_driven"] else "plan-driven"
                        push(
                            f"🔍 **Researcher** round {data['iteration']} ({mode}): "
                            f"+{len(data['new_findings'])} findings "
                            f"(total {data['total_findings']})"
                        )

                    elif event_name == "draft":
                        result["draft"] = data["text"]
                        push(
                            f"✍️ **Writer** produced draft v{data['iteration']} "
                            f"({len(data['text'])} chars)"
                        )

                    elif event_name == "critique":
                        result["critiques"].append(data)
                        push(
                            f"⚖️ **Critic** iter {data['iteration']}: "
                            f"**{data['verdict'].upper()}** — "
                            f"{len(data['gaps'])} gaps, "
                            f"{len(data['unsupported_claims'])} unsupported"
                        )

                    elif event_name == "done":
                        result["iteration"] = data["total_iterations"]
                        result["done"] = True
                        push(
                            f"✅ **Done** — {data['total_iterations']} writer "
                            f"iteration(s), {data['total_findings']} findings"
                        )

                    elif event_name == "error":
                        st.error(f"Backend error: {data.get('message', '')}")
                        push(f"❌ {data.get('message', '')}")
                        return None

        except httpx.ConnectError:
            st.error(
                f"Could not reach backend at {API_URL}. Is `uvicorn app.main:app` running?"
            )
            return None
        except httpx.ReadTimeout:
            st.error(f"Request timed out after {timeout}s. Try a narrower question.")
            return None

    status.update(label="Research complete", state="complete", expanded=False)
    return result


if submitted:
    if not query or len(query.strip()) < 5:
        st.error("Please enter a research question (at least 5 characters).")
        st.stop()

    result = _stream_run(query.strip(), int(max_iterations), int(request_timeout))
    if result and result["done"]:
        st.session_state["last_result"] = result


result = st.session_state.get("last_result")
if result:
    plan = result.get("plan") or {}
    findings = result.get("findings") or []
    critiques = result.get("critiques") or []
    iteration = result.get("iteration", 0)

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Iterations", iteration)
    col_b.metric("Findings", len(findings))
    col_c.metric("Critiques", len(critiques))

    report_tab, plan_tab, findings_tab, critique_tab = st.tabs(
        ["Report", "Plan", "Findings", "Critiques"]
    )

    with report_tab:
        draft = result.get("draft") or "_No draft was produced._"
        st.markdown(draft)

    with plan_tab:
        if plan:
            st.subheader("Objective")
            st.write(plan.get("objective", ""))
            st.subheader("Success criteria")
            for c in plan.get("success_criteria", []):
                st.markdown(f"- {c}")
            st.subheader("Sub-questions")
            for sq in plan.get("sub_questions", []):
                with st.expander(f"{sq['id']}. {sq['question']}"):
                    st.caption(sq.get("rationale", ""))
        else:
            st.info("No plan in response.")

    with findings_tab:
        if not findings:
            st.info("No findings were retrieved.")
        else:
            for i, f in enumerate(findings, 1):
                title = f.get("source_title") or "Source"
                with st.expander(f"[{i}] (sq{f['sub_question_id']}) {f['claim']}"):
                    st.markdown(f"**Evidence:** {f['evidence']}")
                    st.markdown(f"**Source:** [{title}]({f['url']})")

    with critique_tab:
        if not critiques:
            st.info("No critiques were produced.")
        else:
            for c in critiques:
                verdict_color = "green" if c["verdict"] == "done" else "orange"
                st.markdown(
                    f"### Iteration {c['iteration']} — "
                    f":{verdict_color}[**{c['verdict'].upper()}**]"
                )
                st.markdown(f"*{c.get('reasoning', '')}*")
                if c.get("gaps"):
                    st.markdown("**Gaps**")
                    for g in c["gaps"]:
                        st.markdown(f"- {g}")
                if c.get("unsupported_claims"):
                    st.markdown("**Unsupported claims**")
                    for u in c["unsupported_claims"]:
                        st.markdown(f"- {u}")
                st.divider()
else:
    st.info("Enter a research question above and click **Run research**.")
