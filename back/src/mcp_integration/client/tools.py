"""
MCP 서버의 도구 목록 가져오기와 도구 호출 (LangGraph 노드가 바로 쓸 수 있는 동기 함수).

MCP 클라이언트는 비동기(async)이고 LangGraph 노드는 동기 함수라서, run_sync가 둘을 이어 준다.
- 서버 연결은 pool.py가 한 번 만들어 재사용한다 (호출마다 서버를 새로 띄우면 2초씩 든다). REUSE_SERVER_CONNECTION을 False로 하면 예전처럼 호출마다 띄운다.
- 도구가 스스로 실패했을 때는 예외가 아니라 {"is_error": True, "text": 오류 문구}로 돌려준다 (MCP의 방식 그대로).
- 서버를 띄우지 못했거나 시간 초과인 경우에는 예외(TimeoutError 등)가 그대로 올라간다. 처리는 노드가 한다.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from mcp_types import TextContent

from src.const import mcp_config as cfg
from src.const.mcp_config import MCPServerConfig
from src.db.masking import mask_secrets
from src.mcp_integration.client import pool
from src.mcp_integration.client.connection import open_client


def describe_error(exc: BaseException) -> str:
    """사용자와 모델에게 보여 줘도 되는 짧은 오류 설명 (비밀값은 가리고 길이를 줄인다)."""
    return mask_secrets(f"{type(exc).__name__}: {exc}")[:300]


def run_sync(coro):
    """비동기 함수를 동기 코드에서 실행한다. 이미 이벤트 루프가 돌고 있는 환경이면 별도 스레드에서 실행한다."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _tool_list(config: MCPServerConfig, result) -> list[dict]:
    return [
        {
            "server": config.name,
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.input_schema or {"type": "object", "properties": {}},
        }
        for tool in result.tools
    ]


async def _list_tools(config: MCPServerConfig, timeout: float) -> list[dict]:
    async def work():
        async with open_client(config, read_timeout_seconds=timeout) as client:
            return _tool_list(config, await client.list_tools())

    return await asyncio.wait_for(work(), timeout)


def list_tools(config: MCPServerConfig, timeout: float = cfg.LIST_TOOLS_TIMEOUT_SECONDS) -> list[dict]:
    """서버의 도구 목록: [{"server", "name", "description", "input_schema"}, ...]"""
    if cfg.REUSE_SERVER_CONNECTION:
        async def operation(client):
            return _tool_list(config, await client.list_tools())

        return pool.run(config, operation, timeout)
    return run_sync(_list_tools(config, timeout))


def _result_text(result) -> str:
    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    others = len(result.content) - len(texts)
    if others:
        texts.append(f"(텍스트가 아닌 결과 {others}개는 생략했습니다)")
    return "\n".join(texts)


async def _call_tool(config: MCPServerConfig, name: str, arguments: dict[str, Any], timeout: float) -> dict:
    async def work():
        async with open_client(config, read_timeout_seconds=timeout) as client:
            result = await client.call_tool(name, arguments)
        return {"text": _result_text(result), "is_error": bool(result.is_error)}

    return await asyncio.wait_for(work(), timeout)


def call_tool(
    config: MCPServerConfig,
    name: str,
    arguments: dict[str, Any],
    timeout: float = cfg.CALL_TOOL_TIMEOUT_SECONDS,
) -> dict:
    """도구를 호출한다. 돌려주는 값: {"text": 결과 글, "is_error": 도구가 스스로 실패했는지}"""
    if cfg.REUSE_SERVER_CONNECTION:
        async def operation(client):
            result = await client.call_tool(name, arguments)
            return {"text": _result_text(result), "is_error": bool(result.is_error)}

        return pool.run(config, operation, timeout)
    return run_sync(_call_tool(config, name, arguments, timeout))
