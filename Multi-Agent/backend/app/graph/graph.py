from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, HttpUrl

from app.graph.state import Critique, Finding, ResearchPlan, ResearchState
from app.llm import llm
from app.tools.web_search import web_search

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompts (loaded once at module import).
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


PLANNER_SYSTEM_PROMPT = _load_prompt("planner.md")
RESEARCHER_SYSTEM_PROMPT = _load_prompt("researcher.md")
WRITER_SYSTEM_PROMPT = _load_prompt("writer.md")
CRITIC_SYSTEM_PROMPT = _load_prompt("critic.md")


# ---------------------------------------------------------------------------
# LLM extraction shapes.  `iteration` / `sub_question_id` / `retrieved_at` are
# set by the node, not the LLM, so they live outside these models.
# ---------------------------------------------------------------------------

class _FindingExtraction(BaseModel):
    claim: str
    evidence: str
    url: HttpUrl
    source_title: str | None = None


class _ExtractionResult(BaseModel):
    findings: list[_FindingExtraction]


class _CritiqueExtraction(BaseModel):
    gaps: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    verdict: Literal["continue", "done"]
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_results(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"[{i}] {r.get('title', '')}\n"
            f"URL: {r.get('link', '')}\n"
            f"Snippet: {r.get('snippet', '')}"
        )
    return "\n\n".join(lines)


def _format_findings(findings: list[Finding]) -> str:
    lines = []
    for i, f in enumerate(findings, 1):
        title = f.source_title or "Source"
        lines.append(
            f"[{i}] {f.claim}\n"
            f"    Evidence: {f.evidence}\n"
            f"    Source: {title} ({f.url})"
        )
    return "\n\n".join(lines)


def _format_critique_feedback(critique: Critique) -> str:
    lines = [
        f"Previous critique (iteration {critique.iteration}) — address this in your rewrite:",
        f"  Reasoning: {critique.reasoning}",
    ]
    if critique.gaps:
        lines.append("  Gaps to fill (cite new findings that cover these):")
        lines.extend(f"    - {g}" for g in critique.gaps)
    if critique.unsupported_claims:
        lines.append("  Unsupported claims to remove or re-cite:")
        lines.extend(f"    - {c}" for c in critique.unsupported_claims)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

_planner_chain = (
    ChatPromptTemplate.from_messages([
        ("system", PLANNER_SYSTEM_PROMPT),
        ("user", "Research question: {query}"),
    ])
    | llm.with_structured_output(ResearchPlan)
)


def planner_node(state: ResearchState) -> dict:
    logger.info("planner: query=%r", state["query"])
    plan: ResearchPlan = _planner_chain.invoke({"query": state["query"]})
    logger.info(
        "planner done: %d sub-questions, %d success-criteria",
        len(plan.sub_questions),
        len(plan.success_criteria),
    )
    return {"plan": plan}


_researcher_chain = (
    ChatPromptTemplate.from_messages([
        ("system", RESEARCHER_SYSTEM_PROMPT),
        ("user", "Sub-question: {sub_question}\n\nSearch results:\n{results}"),
    ])
    | llm.with_structured_output(_ExtractionResult, method="function_calling")
)


def researcher_node(state: ResearchState) -> dict:
    plan = state["plan"]
    if plan is None:
        return {"findings": []}

    critiques = state.get("critiques") or []
    existing_urls = {str(f.url) for f in state.get("findings") or []}

    # On the first pass, work through the planner's sub-questions.
    # On follow-up passes, search the critic's gaps directly — otherwise
    # we just collect the same findings again and the critic keeps complaining.
    if critiques and critiques[-1].gaps:
        gaps = critiques[-1].gaps
        id_base = max((sq.id for sq in plan.sub_questions), default=0) + 100 * len(critiques)
        targets = [
            (id_base + idx, f"{gap} (context: {plan.objective})")
            for idx, gap in enumerate(gaps, start=1)
        ]
        logger.info("researcher: gap-driven round (%d gaps)", len(gaps))
    else:
        targets = [(sq.id, sq.question) for sq in plan.sub_questions]
        logger.info("researcher: plan-driven round (%d sub-questions)", len(targets))

    new_findings: list[Finding] = []
    dropped_dupes = 0
    for sq_id, query in targets:
        raw_results = web_search(query)
        if not raw_results:
            continue
        extraction: _ExtractionResult = _researcher_chain.invoke({
            "sub_question": query,
            "results": _format_results(raw_results),
        })
        for fe in extraction.findings:
            url_str = str(fe.url)
            if url_str in existing_urls:
                dropped_dupes += 1
                continue
            existing_urls.add(url_str)
            new_findings.append(Finding(
                sub_question_id=sq_id,
                claim=fe.claim,
                evidence=fe.evidence,
                url=fe.url,
                source_title=fe.source_title,
            ))

    logger.info(
        "researcher done: %d new findings (dropped %d duplicates)",
        len(new_findings),
        dropped_dupes,
    )
    return {"findings": new_findings}


_writer_prompt = ChatPromptTemplate.from_messages([
    ("system", WRITER_SYSTEM_PROMPT),
    ("user",
     "Objective: {objective}\n\n"
     "Success criteria:\n{criteria}\n\n"
     "Findings:\n{findings}\n\n"
     "{critique_section}"
     "Write the report now."),
])
_writer_chain = _writer_prompt | llm


def writer_node(state: ResearchState) -> dict:
    plan = state["plan"]
    findings = state["findings"]

    if plan is None or not findings:
        logger.warning("writer: no plan or no findings; emitting placeholder draft")
        return {"draft": "_No findings were retrieved; cannot draft a report._"}

    critiques = state.get("critiques") or []
    critique_section = (
        _format_critique_feedback(critiques[-1]) + "\n\n" if critiques else ""
    )

    logger.info(
        "writer: %d findings, %s",
        len(findings),
        f"rewriting with critique iter {critiques[-1].iteration}" if critiques else "first draft",
    )
    response = _writer_chain.invoke({
        "objective": plan.objective,
        "criteria": "\n".join(f"- {c}" for c in plan.success_criteria),
        "findings": _format_findings(findings),
        "critique_section": critique_section,
    })

    return {"draft": response}


_critic_prompt = ChatPromptTemplate.from_messages([
    ("system", CRITIC_SYSTEM_PROMPT),
    ("user",
     "Objective: {objective}\n\n"
     "Success criteria:\n{criteria}\n\n"
     "Findings available:\n{findings}\n\n"
     "{prior_critique_section}"
     "Draft:\n{draft}\n\n"
     "Critique the draft now."),
])
_critic_chain = _critic_prompt | llm.with_structured_output(
    _CritiqueExtraction, method="function_calling"
)


def critic_node(state: ResearchState) -> dict:
    plan = state["plan"]
    draft = state.get("draft", "")
    findings = state.get("findings") or []
    prior_critiques = state.get("critiques") or []
    next_iteration = state.get("iteration", 0) + 1

    if plan is None or not draft:
        logger.warning("critic: no plan or no draft; auto-terminating loop")
        critique = Critique(
            iteration=next_iteration,
            verdict="done",
            reasoning="No plan or draft available to critique.",
        )
        return {"critiques": [critique], "iteration": next_iteration}

    prior_critique_section = ""
    if prior_critiques:
        prev = prior_critiques[-1]
        lines = [
            f"Your previous critique (iteration {prev.iteration}) flagged:",
            f"  Gaps: {prev.gaps or '(none)'}",
            f"  Unsupported claims: {prev.unsupported_claims or '(none)'}",
            "Judge whether this rewrite addresses those items. Do NOT invent fresh,",
            "unrelated gaps if the writer made reasonable progress on the prior ones.",
        ]
        prior_critique_section = "\n".join(lines) + "\n\n"

    logger.info("critic: iteration=%d, %d findings", next_iteration, len(findings))
    extraction: _CritiqueExtraction = _critic_chain.invoke({
        "objective": plan.objective,
        "criteria": "\n".join(f"- {c}" for c in plan.success_criteria),
        "findings": _format_findings(findings) if findings else "(no findings)",
        "prior_critique_section": prior_critique_section,
        "draft": draft,
    })

    critique = Critique(
        iteration=next_iteration,
        gaps=extraction.gaps,
        unsupported_claims=extraction.unsupported_claims,
        verdict=extraction.verdict,
        reasoning=extraction.reasoning,
    )
    logger.info(
        "critic done: verdict=%s, %d gaps, %d unsupported",
        critique.verdict,
        len(critique.gaps),
        len(critique.unsupported_claims),
    )
    return {"critiques": [critique], "iteration": next_iteration}


# ---------------------------------------------------------------------------
# Conditional edge
# ---------------------------------------------------------------------------

def route_from_critic(state: ResearchState):
    critiques = state["critiques"]
    latest = critiques[-1]

    if latest.verdict == "done":
        logger.info("router: END (critic said done)")
        return END

    if state["iteration"] >= state["max_iterations"]:
        logger.info("router: END (hit max_iterations=%d)", state["max_iterations"])
        return END

    # No-progress short-circuit: if the critic just got a fresh rewrite and
    # still returns the same (or more) gaps as last round, another loop won't
    # help — we're stuck on something web search can't supply.
    if len(critiques) >= 2:
        prev = critiques[-2]
        if latest.gaps and len(latest.gaps) >= len(prev.gaps):
            logger.info(
                "router: END (no progress; gaps %d->%d)",
                len(prev.gaps),
                len(latest.gaps),
            )
            return END

    logger.info("router: -> researcher_node (continue, %d gaps)", len(latest.gaps))
    return "researcher_node"


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

graph = StateGraph(ResearchState)
graph.add_node("planner_node", planner_node)
graph.add_node("researcher_node", researcher_node)
graph.add_node("writer_node", writer_node)
graph.add_node("critic_node", critic_node)

graph.add_edge("planner_node", "researcher_node")
graph.add_edge("researcher_node", "writer_node")
graph.add_edge("writer_node", "critic_node")

graph.add_conditional_edges(
    "critic_node",
    route_from_critic,
    {"researcher_node": "researcher_node", END: END},
)

graph.set_entry_point("planner_node")

research_graph = graph.compile()
