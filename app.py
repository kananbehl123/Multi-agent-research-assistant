"""
ResearchAI — Streamlit front end for the multi-agent research pipeline.

Run with:  streamlit run app.py

Runs the steps from pipeline.py one at a time so the UI can show live
progress, timing and rate-limit countdowns for each one.
"""

import os
import re
import time
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from pipeline import STEPS, is_rate_limit, is_daily_quota

st.set_page_config(
    page_title="ResearchAI",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# STYLE
# ============================================================

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&display=swap');

:root {
    --paper: #EEF2EC;
    --ink: #1D2B36;
    --ink-soft: #52616B;
    --rule: #C9D3CB;
    --accent: #0F6E6E;
    --amber: #B7791F;
}

html, body, [class*="css"], .stApp, button, input, textarea {
    font-family: 'IBM Plex Sans', system-ui, sans-serif;
}

.stApp { background: var(--paper); color: var(--ink); }

.block-container { max-width: 1100px; padding-top: 2.5rem; }

/* Masthead: the question is the hero */
.masthead h1 {
    font-family: 'Source Serif 4', Georgia, serif;
    font-weight: 700;
    font-size: clamp(2.1rem, 4.5vw, 3.2rem);
    line-height: 1.08;
    letter-spacing: -0.02em;
    color: var(--ink);
    margin: 0 0 0.5rem 0;
}
.masthead p {
    color: var(--ink-soft);
    font-size: 1.02rem;
    max-width: 62ch;
    margin: 0 0 1.4rem 0;
}

/* Topic input */
.stTextInput input {
    font-size: 1.1rem;
    padding: 0.8rem 1rem;
    border: 1.5px solid var(--ink);
    border-radius: 6px;
    background: #fff;
}
.stTextInput input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(15,110,110,0.18);
}

/* Primary button */
div.stButton > button[kind="primary"],
div.stFormSubmitButton > button {
    background: var(--accent);
    border: none;
    border-radius: 6px;
    font-weight: 600;
    padding: 0.65rem 1.4rem;
}
div.stButton > button[kind="primary"]:hover,
div.stFormSubmitButton > button:hover { background: #0B5757; }

/* Pipeline legend */
.legend { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; border-top: 1.5px solid var(--ink); margin-top: 1.8rem; }
.legend div { padding: 0.9rem 1rem 0.9rem 0; border-right: 1px solid var(--rule); margin-right: 1rem; }
.legend div:last-child { border-right: none; }
.legend b { display: block; font-weight: 600; color: var(--ink); margin-bottom: 0.2rem; }
.legend span { color: var(--ink-soft); font-size: 0.9rem; }
@media (max-width: 760px) { .legend { grid-template-columns: 1fr 1fr; } }

/* Report typography */
.report-body, .report-body p, .report-body li {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 1.08rem;
    line-height: 1.75;
    color: var(--ink);
}
.report-body { max-width: 72ch; }
.report-body h1, .report-body h2, .report-body h3 {
    font-family: 'Source Serif 4', Georgia, serif;
    color: var(--ink);
}

/* Score block */
.score { display: flex; align-items: baseline; gap: 0.4rem; }
.score .n { font-family: 'Source Serif 4', Georgia, serif; font-size: 3rem; font-weight: 700; color: var(--accent); line-height: 1; }
.score .d { color: var(--ink-soft); font-size: 1.1rem; }
.score.low .n { color: var(--amber); }

a { color: var(--accent); }
</style>
""",
    unsafe_allow_html=True,
)

# ============================================================
# SESSION STATE
# ============================================================

if "runs" not in st.session_state:
    st.session_state.runs = []          # list of completed run dicts
if "active" not in st.session_state:
    st.session_state.active = None      # index into runs
if "topic_input" not in st.session_state:
    st.session_state.topic_input = ""


# ============================================================
# HELPERS
# ============================================================

def extract_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s\)\]\"'<>]+", text or "")
    seen, out = set(), []
    for u in urls:
        u = u.rstrip(".,;:")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def parse_score(feedback: str):
    m = re.search(r"Score:\s*\**\s*(\d+(?:\.\d+)?)\s*/\s*10", feedback or "", re.I)
    return float(m.group(1)) if m else None


def slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_")[:60] or "report"


def build_bundle(run: dict) -> str:
    return (
        f"# Research report: {run['topic']}\n\n"
        f"_Generated {run['timestamp']}_\n\n"
        f"{run['report']}\n\n---\n\n"
        f"## Critic review\n\n{run['feedback']}\n\n---\n\n"
        f"## Search results\n\n{run['search_results']}\n\n---\n\n"
        f"## Scraped content\n\n{run['scraped_content']}\n"
    )


def set_topic(t: str):
    st.session_state.topic_input = t


# ============================================================
# RUN THE PIPELINE WITH LIVE STATUS
# ============================================================

def make_waiter(box, label):
    """Countdown shown in a step's status while waiting out a rate limit."""
    def wait(seconds):
        for remaining in range(int(seconds), 0, -1):
            box.update(label=f"{label}: rate limit hit, retrying in {remaining}s", state="running")
            time.sleep(1)
        box.update(label=f"{label}…", state="running")
    return wait


def explain_error(name, e):
    if is_rate_limit(e) and is_daily_quota(e):
        return (
            "You've used today's free Gemini quota. Try again tomorrow, enable "
            "billing in Google AI Studio, or set GEMINI_MODEL in .env to a "
            "different model (each model has its own quota)."
        )
    if is_rate_limit(e):
        return (
            f"The {name.lower()} step was still rate limited after several retries. "
            "Wait a minute and run it again."
        )
    return (
        f"The {name.lower()} step stopped with: {e}\n\n"
        "Check that your API keys are set and that the model name in agents.py "
        "is available to your account."
    )


def run_pipeline(topic: str):
    state = {}
    timings = {}
    overall = st.progress(0.0, text="Starting")

    for i, (name, doing, fn) in enumerate(STEPS):
        label = f"{i + 1}. {doing}"
        overall.progress(i / len(STEPS), text=f"Step {i + 1} of {len(STEPS)}: {doing}")
        with st.status(f"{label}…", expanded=False) as box:
            t0 = time.perf_counter()
            try:
                fn(topic, state, on_wait=make_waiter(box, label))
            except Exception as e:
                box.update(label=f"{i + 1}. {name} failed", state="error", expanded=True)
                overall.empty()
                st.error(explain_error(name, e))
                with st.expander("Full traceback"):
                    st.exception(e)
                return None
            dt = time.perf_counter() - t0
            timings[name] = dt
            done = f"{i + 1}. {name} done in {dt:.1f}s"
            if name == "Read":
                done += f" ({state.get('scraped_count', 0)} pages read)"
            box.update(label=done, state="complete")

    overall.progress(1.0, text="Done")
    time.sleep(0.3)
    overall.empty()

    return {
        "topic": topic,
        "timestamp": datetime.now().strftime("%d %b %Y, %H:%M"),
        "sources": state.get("sources", []),
        "search_results": state.get("search_results", ""),
        "scraped_content": state.get("scraped_content", ""),
        "report": state.get("report", ""),
        "feedback": state.get("feedback", ""),
        "timings": timings,
    }


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("### ResearchAI")
    st.caption("Search, read, write and review in one run.")

    st.markdown("**API keys**")
    for key in ["GEMINI_API_KEY", "TAVILY_API_KEY"]:
        if os.getenv(key):
            st.markdown(f"✅ `{key}`")
        else:
            st.markdown(f"⚠️ `{key}` missing from .env")

    st.divider()
    st.markdown("**Past runs**")
    if not st.session_state.runs:
        st.caption("Reports you generate appear here for this session.")
    else:
        for idx in reversed(range(len(st.session_state.runs))):
            r = st.session_state.runs[idx]
            label = r["topic"] if len(r["topic"]) <= 34 else r["topic"][:32] + "…"
            if st.button(
                label,
                key=f"hist_{idx}",
                use_container_width=True,
                type="primary" if idx == st.session_state.active else "secondary",
            ):
                st.session_state.active = idx
                st.rerun()
        if st.button("Clear history", use_container_width=True):
            st.session_state.runs = []
            st.session_state.active = None
            st.rerun()

    st.divider()
    st.caption("LangChain · Gemini · Tavily")


# ============================================================
# MASTHEAD + INPUT
# ============================================================

st.markdown(
    """
<div class="masthead">
  <h1>What should we research?</h1>
  <p>Give a topic. Four agents search the web, read the best source,
  write a structured report and then score it for accuracy.</p>
</div>
""",
    unsafe_allow_html=True,
)

with st.form("topic_form", border=False):
    c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
    with c1:
        topic = st.text_input(
            "Research topic",
            key="topic_input",
            placeholder="e.g. Stormwater harvesting in Australian cities",
            label_visibility="collapsed",
        )
    with c2:
        submitted = st.form_submit_button("Start research", use_container_width=True)

examples = [
    "AI in healthcare diagnostics",
    "Green hydrogen supply chains",
    "Microplastics in drinking water",
]
ex_cols = st.columns(len(examples) + 2)
ex_cols[0].caption("Try:")
for col, ex in zip(ex_cols[1:], examples):
    col.button(ex, key=f"ex_{ex}", on_click=set_topic, args=(ex,), use_container_width=True)


# ============================================================
# RUN
# ============================================================

if submitted:
    clean = (topic or "").strip()
    if not clean:
        st.warning("Type a topic first, then press Start research.")
    else:
        result = run_pipeline(clean)
        if result:
            st.session_state.runs.append(result)
            st.session_state.active = len(st.session_state.runs) - 1
            st.rerun()


# ============================================================
# EMPTY STATE
# ============================================================

active = st.session_state.active
if active is None or active >= len(st.session_state.runs):
    st.markdown(
        """
<div class="legend">
  <div><b>1. Search</b><span>Finds recent sources with Tavily.</span></div>
  <div><b>2. Read</b><span>Scrapes the top three pages.</span></div>
  <div><b>3. Write</b><span>Drafts a report from what was found.</span></div>
  <div><b>4. Review</b><span>Scores the draft against the research.</span></div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.stop()


# ============================================================
# RESULTS
# ============================================================

run = st.session_state.runs[active]
score = parse_score(run["feedback"])
sources = [s["url"] for s in run.get("sources", []) if s.get("url")] or extract_urls(
    run["search_results"] + "\n" + run["scraped_content"]
)
source_titles = {s["url"]: s["title"] for s in run.get("sources", [])}
words = len(run["report"].split())
total_time = sum(run["timings"].values())

st.divider()
st.markdown(f"## {run['topic']}")
st.caption(f"Generated {run['timestamp']}")

m1, m2, m3, m4 = st.columns(4)
with m1:
    if score is not None:
        cls = "score low" if score < 7 else "score"
        st.markdown(
            f'<div class="{cls}"><span class="n">{score:g}</span><span class="d">/ 10 critic score</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.metric("Critic score", "n/a")
m2.metric("Sources found", len(sources))
m3.metric("Report length", f"{words:,} words")
m4.metric("Total time", f"{total_time:.0f}s")

d1, d2, _ = st.columns([1, 1, 2])
d1.download_button(
    "Download report (.md)",
    data=run["report"],
    file_name=f"{slugify(run['topic'])}_report.md",
    mime="text/markdown",
    use_container_width=True,
)
d2.download_button(
    "Download everything (.md)",
    data=build_bundle(run),
    file_name=f"{slugify(run['topic'])}_full.md",
    mime="text/markdown",
    use_container_width=True,
)

tab_report, tab_review, tab_sources, tab_raw = st.tabs(
    ["Report", "Critic review", f"Sources ({len(sources)})", "Raw agent output"]
)

with tab_report:
    with st.container(border=True):
        st.markdown('<div class="report-body">', unsafe_allow_html=True)
        st.markdown(run["report"] or "_The writer returned an empty report._")
        st.markdown("</div>", unsafe_allow_html=True)

with tab_review:
    with st.container(border=True):
        st.markdown(run["feedback"] or "_The critic returned no feedback._")

with tab_sources:
    if sources:
        for u in sources:
            st.markdown(f"- [{source_titles.get(u, u)}]({u})")
    else:
        st.info("No URLs were found in the search or scraped output.")

with tab_raw:
    st.markdown("**Search agent**")
    with st.container(border=True, height=320):
        st.markdown(run["search_results"] or "_Empty_")
    st.markdown("**Reader agent**")
    with st.container(border=True, height=320):
        st.markdown(run["scraped_content"] or "_Empty_")
    st.markdown("**Step timings**")
    st.dataframe(
        [{"Step": k, "Seconds": round(v, 1)} for k, v in run["timings"].items()],
        hide_index=True,
        use_container_width=True,
    )