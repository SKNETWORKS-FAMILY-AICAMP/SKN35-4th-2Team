"""
서버에 등록할 도구 모음. 도구 파일마다 register(mcp) 함수가 있고, 여기서 한꺼번에 등록한다.

도구를 추가하려면 이 폴더에 새 파일을 만들고 TOOL_MODULES에 넣는다.
모델은 도구가 많을수록 잘못 고르기 쉬워서, 5~6개를 넘기지 않고 도구마다 "언제 쓰는지"를 설명(docstring)에 구체적으로 쓴다.

| 파일 | 도구 | 하는 일 |
|---|---|---|
| version_tools.py | get_latest_version | PyPI에서 패키지의 최신 정식 버전 조회 |
| version_tools.py | check_version_compat | 사용자의 패키지 버전들이 서로 맞는지 계산 |
| github_tools.py | search_github_issues | LangChain, LangGraph, MCP 저장소의 이슈 검색 |
| github_tools.py | get_github_issue | 이슈 한 건의 본문과 댓글 |
| symbol_tools.py | check_symbol_exists | 함수, 클래스, 모듈이 설치된 버전에 있는지 확인 (환각 방지) |
"""

from src.mcp_integration.server.tools import github_tools, symbol_tools, version_tools

TOOL_MODULES = (version_tools, github_tools, symbol_tools)


def register_all(mcp) -> None:
    for module in TOOL_MODULES:
        module.register(mcp)
