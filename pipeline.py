"""
Research pipeline.

Search and Read call Tavily and the scraper directly (no LLM calls).
Write and Review use Gemini, with automatic wait-and-retry on rate limits.
A full run makes only 2 Gemini calls.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor

from tools import client, scrape_url
from agents import writer_chain, critic_chain


MAX_SOURCES = 6      # search results to keep
SCRAPE_TOP = 3       # pages to read in full
MAX_ATTEMPTS = 4     # attempts per LLM step before giving up


# ============================================================
# HELPERS
# ============================================================

def to_text(content) -> str:
    """Gemini can return content as a list of blocks; flatten it."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type", "text") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(p for p in parts if p)
    return str(content)


def is_rate_limit(err: Exception) -> bool:
    msg = str(err)
    return "RESOURCE_EXHAUSTED" in msg or " 429" in msg or msg.startswith("429")


def is_daily_quota(err: Exception) -> bool:
    return "PerDay" in str(err)


def retry_delay(err: Exception) -> float:
    m = re.search(r"retry in ([\d.]+)s", str(err))
    return (float(m.group(1)) + 2) if m else 30.0


def with_retry(fn, on_wait=None):
    """Run fn(); on a per-minute rate limit, wait the suggested delay and retry."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:
            if not is_rate_limit(e) or is_daily_quota(e) or attempt == MAX_ATTEMPTS:
                raise
            delay = retry_delay(e)
            if on_wait:
                on_wait(delay)
            else:
                print(f"  Rate limited. Retrying in {delay:.0f}s...")
                time.sleep(delay)


# ============================================================
# STEPS  (each takes topic, state, on_wait and fills state)
# ============================================================

def step_search(topic: str, state: dict, on_wait=None):
    res = client.search(query=topic, max_results=MAX_SOURCES)
    results = res.get("results", [])
    if not results:
        raise RuntimeError("Tavily returned no results. Try rewording the topic.")

    state["sources"] = [
        {
            "title": r.get("title", "Untitled"),
            "url": r.get("url", ""),
            "snippet": (r.get("content") or "")[:500],
        }
        for r in results
    ]
    state["search_results"] = "\n".join(
        f"Title: {s['title']}\nURL: {s['url']}\nSnippet: {s['snippet']}\n"
        for s in state["sources"]
    )


def step_read(topic: str, state: dict, on_wait=None):
    urls = [s["url"] for s in state["sources"][:SCRAPE_TOP] if s["url"]]

    with ThreadPoolExecutor(max_workers=max(1, len(urls))) as pool:
        texts = list(pool.map(lambda u: scrape_url.invoke({"url": u}), urls))

    parts = [
        f"SOURCE: {u}\n{t}"
        for u, t in zip(urls, texts)
        if t and not t.startswith("Could not scrape")
    ]
    state["scraped_count"] = len(parts)
    state["scraped_content"] = (
        "\n\n---\n\n".join(parts)
        if parts
        else "No pages could be scraped. The report is based on search snippets only."
    )


def step_write(topic: str, state: dict, on_wait=None):
    state["research_combined"] = (
        f"SEARCH RESULTS:\n{state['search_results']}\n\n"
        f"DETAILED SCRAPED CONTENT:\n{state['scraped_content']}"
    )
    out = with_retry(
        lambda: writer_chain.invoke({
            "topic": topic,
            "research": state["research_combined"],
        }),
        on_wait,
    )
    state["report"] = to_text(out)


def step_critique(topic: str, state: dict, on_wait=None):
    out = with_retry(
        lambda: critic_chain.invoke({
            "article": state["report"],
            "research": state["research_combined"],
        }),
        on_wait,
    )
    state["feedback"] = to_text(out)


# (name, what it's doing, function)
STEPS = [
    ("Search", "Searching the web", step_search),
    ("Read", "Reading the top sources", step_read),
    ("Write", "Drafting the report", step_write),
    ("Review", "Reviewing the draft", step_critique),
]


# ============================================================
# FULL RUN (CLI)
# ============================================================

def run_research_pipeline(topic: str) -> dict:
    state = {}
    for i, (name, doing, fn) in enumerate(STEPS, start=1):
        print("\n" + "=" * 50)
        print(f"STEP {i} - {doing}...")
        print("=" * 50)
        fn(topic, state)

    print("\nFINAL REPORT:\n")
    print(state["report"])
    print("\nCRITIC REPORT:\n")
    print(state["feedback"])
    return state


if __name__ == "__main__":
    topic = input("\nEnter a research topic: ")
    run_research_pipeline(topic)
    print("\n" + "=" * 50)
    print("RESEARCH PIPELINE COMPLETED")
    print("=" * 50)