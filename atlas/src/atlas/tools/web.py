"""Web tools — search and fetch.

`web_search` tries providers in this order, using whichever is configured:
  1. Tavily          (TAVILY_API_KEY) — recommended, purpose-built for LLM search
  2. Brave Search    (BRAVE_API_KEY)
  3. Serper          (SERPER_API_KEY) — Google results
  4. DuckDuckGo HTML (no key, no signup, rate-limited)

`fetch_url` is a simple requests + BeautifulSoup HTML-to-text fetcher.

Nothing here requires Atlas-specific infrastructure.
"""

from __future__ import annotations

import os
import re
from typing import Optional

import requests

from ..storage import Storage
from .base import ToolHandler


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ----- search providers -----


def _search_tavily(query: str, api_key: str) -> Optional[dict]:
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": 8,
                "include_answer": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data.get("answer", "") or ""
        sources = [
            {"title": r.get("title", ""), "url": r.get("url", "")}
            for r in data.get("results", [])
        ]
        if not answer:
            answer = "\n".join(
                f"- {r.get('title', '')}: {r.get('content', '')[:300]}"
                for r in data.get("results", [])[:5]
            )
        return {"answer": answer, "sources": sources, "provider": "tavily"}
    except Exception:
        return None


def _search_brave(query: str, api_key: str) -> Optional[dict]:
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 8},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("web", {}).get("results", []) or []
        sources = [
            {"title": r.get("title", ""), "url": r.get("url", "")} for r in results
        ]
        answer = "\n".join(
            f"- {r.get('title', '')}: {r.get('description', '')[:300]}"
            for r in results[:5]
        )
        return {"answer": answer or "No results.", "sources": sources, "provider": "brave"}
    except Exception:
        return None


def _search_serper(query: str, api_key: str) -> Optional[dict]:
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": 8},
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        organic = data.get("organic", []) or []
        sources = [
            {"title": r.get("title", ""), "url": r.get("link", "")} for r in organic
        ]
        answer_box = data.get("answerBox", {}).get("answer") or data.get("answerBox", {}).get("snippet")
        if answer_box:
            answer = str(answer_box)
        else:
            answer = "\n".join(
                f"- {r.get('title', '')}: {r.get('snippet', '')[:300]}"
                for r in organic[:5]
            )
        return {"answer": answer or "No results.", "sources": sources, "provider": "serper"}
    except Exception:
        return None


def _search_duckduckgo(query: str) -> Optional[dict]:
    """No-key fallback. Scrapes the HTML interface — fragile but functional."""
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": _USER_AGENT},
            timeout=20,
        )
        resp.raise_for_status()
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for result in soup.select(".result")[:8]:
            link_el = result.select_one("a.result__a")
            snippet_el = result.select_one(".result__snippet")
            if not link_el:
                continue
            url = link_el.get("href", "")
            # DDG wraps real URLs in a redirect; try to unwrap
            m = re.search(r"uddg=([^&]+)", url)
            if m:
                from urllib.parse import unquote
                url = unquote(m.group(1))
            results.append({
                "title": link_el.get_text(strip=True),
                "url": url,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            })
        if not results:
            return None
        answer = "\n".join(
            f"- {r['title']}: {r['snippet'][:300]}" for r in results[:5]
        )
        return {
            "answer": answer,
            "sources": [{"title": r["title"], "url": r["url"]} for r in results],
            "provider": "duckduckgo",
        }
    except Exception:
        return None


class WebSearchHandler(ToolHandler):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for current information. Use when you need news, "
            "company info, market data, or anything requiring up-to-date sources. "
            "Returns a synthesized answer and a list of source URLs."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
            },
            "required": ["query"],
        }

    def execute(self, args: dict, storage: Storage, **kwargs) -> dict:
        query = self.validate_string(args.get("query"), None, 500)
        if not query:
            return self.error_response("MISSING_QUERY", "query is required", retryable=False)

        tavily_key = os.getenv("TAVILY_API_KEY")
        brave_key = os.getenv("BRAVE_API_KEY")
        serper_key = os.getenv("SERPER_API_KEY")

        result = None
        if tavily_key:
            result = _search_tavily(query, tavily_key)
        if result is None and brave_key:
            result = _search_brave(query, brave_key)
        if result is None and serper_key:
            result = _search_serper(query, serper_key)
        if result is None:
            result = _search_duckduckgo(query)

        if result is None:
            return self.error_response(
                "SEARCH_ERROR",
                "All search providers failed. Set TAVILY_API_KEY, BRAVE_API_KEY, "
                "or SERPER_API_KEY for reliable search.",
                retryable=True,
            )

        return self.success_response(query=query, **result)


class FetchUrlHandler(ToolHandler):
    @property
    def name(self) -> str:
        return "fetch_url"

    @property
    def description(self) -> str:
        return (
            "Fetch and read the text content of a web page. Use AFTER web_search "
            "to read a specific page in detail. Returns extracted text (HTML stripped). "
            "Workflow: web_search → fetch_url on promising results → synthesize."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to fetch (must start with http:// or https://).",
                }
            },
            "required": ["url"],
        }

    def execute(self, args: dict, storage: Storage, **kwargs) -> dict:
        url = self.validate_string(args.get("url"), None, 2000)
        if not url:
            return self.error_response("MISSING_URL", "url is required", retryable=False)
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "text/html" in content_type or "application/xhtml" in content_type:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                text = re.sub(r"\n{3,}", "\n\n", text)
            elif "application/json" in content_type:
                import json as _json
                text = _json.dumps(resp.json(), indent=2)
            else:
                text = resp.text

            max_chars = 15000
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars] + "\n\n[... content truncated at 15,000 chars]"

            return self.success_response(
                url=resp.url,
                content=text,
                truncated=truncated,
                content_type=content_type.split(";")[0].strip(),
            )

        except requests.Timeout:
            return self.error_response("TIMEOUT", f"Page took too long: {url[:100]}", retryable=True)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response else 0
            return self.error_response(
                "HTTP_ERROR",
                f"HTTP {status} for {url[:100]}",
                retryable=status in (429, 500, 502, 503, 504),
            )
        except Exception as e:
            return self.error_response(
                "FETCH_ERROR", f"Could not fetch {url[:100]}: {str(e)[:200]}", retryable=True
            )
