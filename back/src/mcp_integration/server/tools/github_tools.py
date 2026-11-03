"""
GitHub 이슈 도구 두 개 (GitHub 공개 REST API, 토큰 없이 읽기만 한다).

- search_github_issues : 오류 메시지나 키워드로 이슈 검색
- get_github_issue     : 이슈 한 건의 본문과 댓글

- 허용된 저장소(src/const/mcp_config.py의 GITHUB_ALLOWED_REPOS)만 조회한다.
- 토큰이 없어서 요청 제한이 낮다 (시간당 60번, 검색은 분당 10번). 같은 요청은 common.fetch_json이 몇 분간 기억한다.
- 순수 함수(search_issues, get_issue)와 도구 등록(register)을 나눠서 시험하기 쉽게 했다.
"""

import re
from urllib.parse import quote

from mcp.server.mcpserver.exceptions import ToolError

from src.const import mcp_config as cfg
from src.mcp_integration.server.tools import common

_API = "https://api.github.com"
_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
_STATES = ("open", "closed", "all")
_QUALIFIER = re.compile(r"(?<!\S)-?([A-Za-z][\w-]*):(?=\S)")


def _check_repo(repo: str) -> str:
    repo = (repo or "").strip()
    if repo not in cfg.GITHUB_ALLOWED_REPOS:
        raise ToolError(f"'{repo}'는 조회할 수 없는 저장소입니다. 조회할 수 있는 저장소: {', '.join(cfg.GITHUB_ALLOWED_REPOS)}")
    return repo


def sanitize_query(query: str) -> str:
    """검색어 속의 'repo:다른저장소', 'is:pr' 같은 GitHub 검색 한정자를 일반 글자로 바꾼다.
    (오류 메시지의 'ModuleNotFoundError: No module'처럼 콜론 뒤에 공백이 있는 글은 그대로 둔다.)"""
    return _QUALIFIER.sub(lambda m: f"{m.group(1)} ", query).strip()


def _labels(item: dict) -> list[str]:
    return [label["name"] for label in item.get("labels") or [] if isinstance(label, dict) and label.get("name")]


async def search_issues(query: str, repo: str = "", state: str = "all", limit: int = cfg.GITHUB_SEARCH_DEFAULT_RESULTS) -> dict:
    query = sanitize_query(query or "")
    if not query:
        raise ToolError("query가 비어 있습니다. 오류 메시지나 키워드를 넣어야 합니다.")
    if len(query) > 256:
        raise ToolError("query는 256자 이하여야 합니다. 핵심 오류 문구만 남겨서 다시 검색해야 합니다.")
    if state not in _STATES:
        raise ToolError(f"state는 {', '.join(_STATES)} 중 하나여야 합니다 (받은 값: {state}).")
    if not 1 <= limit <= cfg.GITHUB_SEARCH_MAX_RESULTS:
        raise ToolError(f"limit는 1에서 {cfg.GITHUB_SEARCH_MAX_RESULTS} 사이여야 합니다 (받은 값: {limit}).")
    repos = [_check_repo(repo)] if repo else list(cfg.GITHUB_ALLOWED_REPOS)

    q = " ".join([query, "is:issue", *([] if state == "all" else [f"state:{state}"]), *(f"repo:{r}" for r in repos)])
    data = await common.fetch_json(
        f"{_API}/search/issues?q={quote(q)}&per_page={limit}", headers=_HEADERS, what="GitHub 검색"
    )
    items = [
        {
            "repo": item["repository_url"].split("/repos/")[-1],
            "number": item["number"],
            "title": item["title"],
            "state": item["state"],
            "url": item["html_url"],
            "labels": _labels(item),
            "comments": item.get("comments", 0),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "snippet": common.clip(item.get("body"), cfg.GITHUB_SNIPPET_CHARS),
        }
        for item in data.get("items", [])
    ]
    return {
        "query": query,
        "searched_repos": repos,
        "total_count": data.get("total_count", 0),
        "returned": len(items),
        "issues": items,
        "source": "GitHub Search API",
        "retrieved_at": common.now_iso(),
        "note": "검색 결과는 관련도 순입니다. 이슈 내용을 근거로 쓰려면 get_github_issue로 본문과 댓글을 확인하세요."
        if items
        else "검색 결과가 없습니다. 오류 문구를 짧게 줄이거나 다른 키워드로 다시 검색할 수 있습니다.",
    }


async def get_issue(repo: str, number: int, max_comments: int = 5) -> dict:
    repo = _check_repo(repo)
    if not isinstance(number, int) or number <= 0:
        raise ToolError(f"number는 1 이상의 정수여야 합니다 (받은 값: {number}).")
    if not 0 <= max_comments <= cfg.GITHUB_MAX_COMMENTS:
        raise ToolError(f"max_comments는 0에서 {cfg.GITHUB_MAX_COMMENTS} 사이여야 합니다 (받은 값: {max_comments}).")

    issue = await common.fetch_json(f"{_API}/repos/{repo}/issues/{number}", headers=_HEADERS, what=f"{repo} #{number}")
    comments = []
    if max_comments and issue.get("comments"):
        raw = await common.fetch_json(
            f"{_API}/repos/{repo}/issues/{number}/comments?per_page={max_comments}", headers=_HEADERS, what=f"{repo} #{number}의 댓글"
        )
        comments = [
            {
                "author": c["user"]["login"] if c.get("user") else None,
                "author_association": c.get("author_association"),  # OWNER, MEMBER 등: 관리자의 답인지 가늠하는 데 쓴다
                "created_at": c.get("created_at"),
                "url": c.get("html_url"),
                "body": common.clip(c.get("body"), cfg.GITHUB_COMMENT_CHARS),
            }
            for c in raw
        ]
    return {
        "repo": repo,
        "number": number,
        "title": issue["title"],
        "state": issue["state"],
        "state_reason": issue.get("state_reason"),
        "is_pull_request": "pull_request" in issue,
        "url": issue["html_url"],
        "author": issue["user"]["login"] if issue.get("user") else None,
        "labels": _labels(issue),
        "created_at": issue.get("created_at"),
        "closed_at": issue.get("closed_at"),
        "body": common.clip(issue.get("body"), cfg.GITHUB_ISSUE_BODY_CHARS),
        "comments_total": issue.get("comments", 0),
        "comments_returned": len(comments),
        "comments": comments,
        "source": "GitHub REST API",
        "retrieved_at": common.now_iso(),
        "note": "본문과 댓글은 길면 잘려 있습니다. 해결 여부는 state와 관리자(OWNER/MEMBER)의 댓글을 함께 보세요.",
    }


def register(mcp) -> None:
    @mcp.tool()
    async def search_github_issues(query: str, repo: str = "", state: str = "all", limit: int = 5) -> str:
        """LangChain, LangGraph, MCP(python-sdk) GitHub 저장소에서 이슈를 검색한다.

        사용자가 겪는 오류(예외 이름, 오류 메시지, 오류 코드)가 알려진 문제인지, 이슈에 해결책이나 우회 방법이 있는지
        찾을 때 쓴다. 결과의 제목, 상태, URL로 출처를 밝힐 수 있다. 내용을 근거로 쓰려면 get_github_issue로 이어서 확인한다.

        Args:
            query: 검색어. 오류 이름이나 핵심 오류 문구를 짧게 (예: "GraphRecursionError")
            repo: 저장소를 하나로 한정할 때 (langchain-ai/langchain, langchain-ai/langgraph, modelcontextprotocol/python-sdk). 비우면 세 곳 모두 검색
            state: open, closed, all 중 하나 (기본 all). 사용자가 "해결된 이슈"나 "아직 열린 이슈"라고 직접 말했을 때만
                closed 또는 open을 쓰고, 그 밖에는 all로 둔다 (해결책은 이미 닫힌 이슈에 있는 경우가 많다)
            limit: 가져올 개수 1~10 (기본 5)
        """
        return common.dump(await search_issues(query, repo, state, limit))

    @mcp.tool()
    async def get_github_issue(repo: str, number: int, max_comments: int = 5) -> str:
        """GitHub 이슈 또는 풀 리퀘스트(PR) 한 건의 본문, 상태, 댓글을 가져온다.

        search_github_issues로 찾은 이슈의 내용(원인, 해결 방법, 관리자의 답)을 확인하거나, 사용자가 이슈나 PR의 번호나 주소
        (예: .../issues/9163, .../pull/12345)를 직접 알려 주었을 때 쓴다. PR은 설명과 댓글만 가져오고 코드 변경(diff)은 가져오지 않는다.

        Args:
            repo: 저장소 (langchain-ai/langchain, langchain-ai/langgraph, modelcontextprotocol/python-sdk 중 하나)
            number: 이슈 또는 PR 번호 (주소 끝의 숫자)
            max_comments: 가져올 댓글 수 0~10 (기본 5)
        """
        return common.dump(await get_issue(repo, number, max_comments))
