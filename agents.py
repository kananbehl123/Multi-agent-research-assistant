import os
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.rate_limiters import InMemoryRateLimiter

from tools import web_search, scrape_url


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# Free tier allows 5 requests/minute per model. Stay just under it.
# Raise this if you enable billing (paid tier limits are much higher).
REQUESTS_PER_MINUTE = float(os.getenv("GEMINI_RPM", "4"))


# ============================================================
# RATE LIMITER (shared by every agent and chain)
# ============================================================

rate_limiter = InMemoryRateLimiter(
    requests_per_second=REQUESTS_PER_MINUTE / 60,
    check_every_n_seconds=0.5,
    max_bucket_size=1,
)


# ============================================================
# GEMINI LLM
# ============================================================

llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME,
    temperature=0.7,
    google_api_key=os.getenv("GEMINI_API_KEY"),
    max_retries=2,
    rate_limiter=rate_limiter,
)


# ============================================================
# RESEARCH AGENT
# ============================================================

SEARCH_SYSTEM_PROMPT = """You are a research assistant.

Use the web_search tool ONCE with a well-chosen query. Only search a
second time if the first results are clearly irrelevant.

Then summarise the findings, keeping every source's title and URL."""


def build_agent1():

    return create_agent(
        model=llm,
        tools=[web_search, scrape_url],
        system_prompt=SEARCH_SYSTEM_PROMPT,
    )


# ============================================================
# READER AGENT
# ============================================================

READER_SYSTEM_PROMPT = """You are a reading assistant.

Call scrape_url exactly ONCE on the single most relevant URL, then
report the key information from that page along with its URL."""


def build_reader_agent():

    return create_agent(
        model=llm,
        tools=[scrape_url],
        system_prompt=READER_SYSTEM_PROMPT,
    )


# ============================================================
# WRITER AGENT
# ============================================================

writer_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """You are a professional research article writer.

Write accurate, detailed and well-structured articles using the
research information provided.

Do not invent facts that are not supported by the research."""
    ),
    (
        "human",
        """Write a detailed article based on the following information.

Topic:
{topic}

Research gathered:
{research}

Structure the article as:

1. Introduction
2. Main Content
3. Conclusion
4. Sources

Use the research provided as the basis of the article.
Do not invent facts that are not supported by the research.
Be detailed and comprehensive."""
    )
])


writer_chain = writer_prompt | llm | StrOutputParser()


# ============================================================
# CRITIC AGENT
# ============================================================

critic_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """You are a professional content critic.

Your job is to evaluate an article based on the research provided.

Check:
- factual accuracy
- completeness
- structure
- clarity
- whether claims are supported by the research

Do not invent problems that are not actually present."""
    ),
    (
        "human",
        """Critique the following article based on the research provided.

Article:
{article}

Research gathered:
{research}

Respond exactly in the following format:

Score: X/10

Strengths:
- Point 1
- Point 2
- Point 3

Weaknesses:
- Point 1
- Point 2
- Point 3

Suggestions:
- Point 1
- Point 2
- Point 3

Be detailed and specific.
Do not invent problems that are not actually present in the article."""
    )
])


critic_chain = critic_prompt | llm | StrOutputParser()