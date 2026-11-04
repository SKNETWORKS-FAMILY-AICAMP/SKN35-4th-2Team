"""
우리 MCP 서버. 도구는 src/mcp_integration/server/tools/ 아래에 하나씩 파일로 추가한다.

실행 (보통은 직접 실행하지 않는다. 앱이 MCP 클라이언트로 연결할 때 자식 프로세스로 자동으로 뜬다)
    uv run python -m src.mcp_integration.server.server

도구 추가 방법
    1) tools/ 아래에 새 파일을 만들고 register(mcp) 함수 안에서 @mcp.tool()로 도구를 정의한다.
    2) tools/__init__.py의 TOOL_MODULES에 그 파일을 추가한다.
"""

from mcp.server import MCPServer

from src.mcp_integration.server.tools import register_all

mcp = MCPServer("dev-helper")
register_all(mcp)

if __name__ == "__main__":
    mcp.run(transport="stdio")
