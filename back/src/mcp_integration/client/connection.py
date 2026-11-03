"""
MCP 서버 연결 열기.

설정(MCPServerConfig) 하나를 받아 연결된 Client를 돌려준다. 연결 방식(transport)을 바꾸려면 이 파일만 고친다.

- "stdio": 앱이 서버를 같은 PC에서 자식 프로세스로 실행해서 연결한다. 서버를 따로 띄울 필요가 없다.
- "http": 아직 만들지 않았다 (서버 주소로 접속하는 방식. 필요해지면 mcp.client.streamable_http를 써서 여기에 추가한다).
"""

from contextlib import asynccontextmanager

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.const.mcp_config import MCPServerConfig


@asynccontextmanager
async def open_client(config: MCPServerConfig, read_timeout_seconds: float | None = None):
    """async with open_client(config) as client: 로 쓴다. 블록을 벗어나면 연결과 서버 프로세스가 정리된다."""
    if config.transport != "stdio":
        raise NotImplementedError(f"'{config.transport}' 연결 방식은 아직 지원하지 않습니다 (서버: {config.name}).")

    params = StdioServerParameters(
        command=config.command,
        args=list(config.args),
        env=dict(config.env) or None,
        cwd=config.cwd,
    )
    async with Client(stdio_client(params), read_timeout_seconds=read_timeout_seconds) as client:
        yield client
