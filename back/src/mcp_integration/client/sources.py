"""
MCP 도구 결과에서 출처(URL, 제목)를 뽑는다.

    (도구 이름, 도구가 돌려준 글)  -->  [출처, ...]   (출처 모양은 src/db/sources.py의 build_sources와 같다)

- 어떤 도구가 어떤 모양으로 결과를 돌려주는지는 서버의 도구 파일(src/mcp_integration/server/tools)이 정하므로,
  그 결과를 읽는 이 파일은 MCP 폴더에 둔다. 도구의 결과 모양을 바꾸면 이 파일도 같이 고친다.
- 결과 정리 노드(format_results_node)가 도구가 성공할 때마다 불러서 결과 항목에 "sources"로 넣어 둔다.
  DB 쪽 build_sources는 그 "sources"를 모으기만 한다.
- 도구마다 웹 출처가 있는지 여부:
    search_github_issues  이슈마다 URL이 있다
    get_github_issue      이슈 URL
    get_latest_version    PyPI 프로젝트 주소
    check_version_compat  점검한 패키지마다 PyPI 주소
    check_symbol_exists   웹 출처가 없다 (설치된 패키지를 직접 본 결과)
- 읽을 수 없는 글(JSON이 아님, 잘림 등)은 출처 없음으로 처리한다. 출처를 못 뽑는다고 도구 결과 전체를 버리지 않는다.
"""

import json
from typing import Any

_REPO_TECH = {
    "langchain-ai/langchain": "langchain",
    "langchain-ai/langgraph": "langgraph",
    "modelcontextprotocol/python-sdk": "mcp",
}


def _tech_from_package(name: str) -> str | None:
    name = (name or "").lower()
    if name.startswith("langgraph"):
        return "langgraph"
    if name.startswith("langchain"):
        return "langchain"
    if name == "mcp" or name.startswith("mcp-"):
        return "mcp"
    return None


def _issue_source(repo: str, issue: dict) -> dict:
    number = issue.get("number")
    title = issue.get("title") or ""
    state = issue.get("state")
    detail = issue.get("snippet") or issue.get("body") or ""
    return {
        "url": issue.get("url"),
        "title": f"{repo}#{number} {title}".strip(),
        "tech": _REPO_TECH.get(repo),
        "doc_type": "issue",
        "snippet": f"[{state}] {detail}".strip() if state else detail,
    }


def _from_search(data: dict) -> list[dict]:
    return [_issue_source(i.get("repo", ""), i) for i in data.get("issues") or [] if isinstance(i, dict)]


def _from_issue(data: dict) -> list[dict]:
    return [_issue_source(data.get("repo", ""), data)]


def _from_latest_version(data: dict) -> list[dict]:
    package = data.get("package") or ""
    return [
        {
            "url": data.get("url"),
            "title": f"{package} (PyPI)",
            "tech": _tech_from_package(package),
            "version": data.get("latest_version"),
            "doc_type": "release",
            "snippet": data.get("summary"),
        }
    ]


def _from_compat(data: dict) -> list[dict]:
    urls = data.get("sources") or []
    checked = data.get("checked_packages") or []
    found = []
    for index, url in enumerate(urls):
        pin = checked[index] if index < len(checked) else ""
        name, _, version = pin.partition("==")
        found.append(
            {
                "url": url,
                "title": f"{pin} (PyPI)" if pin else "PyPI",
                "tech": _tech_from_package(name),
                "version": version or None,
                "doc_type": "release",
            }
        )
    return found


_EXTRACTORS = {
    "search_github_issues": _from_search,
    "get_github_issue": _from_issue,
    "get_latest_version": _from_latest_version,
    "check_version_compat": _from_compat,
}


def extract_sources(tool: str | None, text: str | None) -> list[dict]:
    """도구 이름과 결과 글에서 출처 목록을 만든다. 출처가 없거나 읽을 수 없으면 빈 목록."""
    # 서버 이름이 앞에 붙은 이름("서버__도구")이면 도구 이름만 쓴다
    name = (tool or "").rsplit("__", 1)[-1]
    extractor = _EXTRACTORS.get(name)
    if extractor is None or not text:
        return []
    try:
        data: Any = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    try:
        return [s for s in extractor(data) if s.get("url")]
    except (AttributeError, TypeError):
        return []
