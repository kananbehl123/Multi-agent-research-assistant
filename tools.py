from langchain.tools import tool
import requests
from tavily import TavilyClient
import os
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# -----------------------------
# Tavily Client
# -----------------------------

tavily_api_key = os.getenv("TAVILY_API_KEY")

client = TavilyClient(
    api_key=tavily_api_key
)


# -----------------------------
# Web Search Tool
# -----------------------------

@tool
def web_search(query: str) -> str:
    """
    Perform a web search using the Tavily API and return
    titles, URLs and snippets for recent information.
    """

    try:
        result = client.search(
            query=query,
            max_results=5
        )

        output = []

        for r in result["results"]:
            output.append(
                f"Title: {r['title']}\n"
                f"URL: {r['url']}\n"
                f"Snippet: {r['content'][:500]}\n"
            )

        return "\n".join(output)

    except Exception as e:
        return f"Web search failed: {str(e)}"


# -----------------------------
# URL Scraping Tool
# -----------------------------

@tool
def scrape_url(url: str) -> str:
    """
    Scrape and return clean text content from a given URL
    for deeper reading.
    """

    try:
        resp = requests.get(
            url,
            timeout=8,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        resp.raise_for_status()

        soup = BeautifulSoup(
            resp.text,
            "html.parser"
        )

        # Remove unnecessary elements
        for tag in soup([
            "script",
            "style",
            "nav",
            "footer"
        ]):
            tag.decompose()

        # Extract clean text
        text = soup.get_text(
            separator=" ",
            strip=True
        )

        return text[:3000]

    except Exception as e:
        return f"Could not scrape URL: {str(e)}"


# -----------------------------
# Optional Tool Testing
# -----------------------------

if __name__ == "__main__":

    print("\nTesting Web Search Tool...\n")

    print(
        web_search.invoke(
            "latest advancements in AI technology"
        )
    )

    print("\nTesting Scraper Tool...\n")

    print(
        scrape_url.invoke(
            "https://www.artificialintelligence-news.com/"
        )
    )