"""
MCP 서버 연결 재사용.

호출마다 서버를 새로 띄우면 한 번에 약 2초가 든다 (2026-10 우리 서버 측정). 이 파일은 서버 프로세스와 연결을 한 번 만들어 두고 다시 쓴다.

- 이벤트 루프를 하나 돌리는 배경 스레드가 연결을 들고 있다. LangGraph 노드와 Streamlit은 호출마다 스레드와 루프가 달라서, 연결을 만든 루프에서만 쓸 수 있기 때문이다.
- 연결은 서버(설정)마다 하나이고, 처음 쓸 때 만든다.
- 서버가 죽었거나 호출이 실패하면 그 연결을 버리고 새로 만들어서 한 번 더 시도한다. 그래도 실패하면 예외가 올라간다 (처리는 노드가 한다).
- 시간 초과가 나면 서버가 멈춘 것일 수 있으므로 연결을 버린다. 다음 호출이 새로 만든다.
- 앱이 끝날 때 서버 프로세스를 정리한다. 재사용을 끄려면 src/const/mcp_config.py의 REUSE_SERVER_CONNECTION을 False로 한다.
"""

import asyncio
import atexit
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from src.const.mcp_config import MCPServerConfig
from src.mcp_integration.client.connection import open_client

_CLOSE_TIMEOUT_SECONDS = 5


class _Connection:
    """연결 하나. 연결을 연 작업이 닫을 때까지 붙들고 있어야 해서(anyio의 규칙) 별도 작업으로 들고 있는다."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.client = None
        self.error: BaseException | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task = asyncio.get_running_loop().create_task(self._hold())

    async def _hold(self) -> None:
        try:
            async with open_client(self.config) as client:
                self.client = client
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # 열지 못한 이유를 기다리는 쪽에 전달한다
            self.error = exc
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            self.client = None
            self._ready.set()

    @property
    def alive(self) -> bool:
        return self.client is not None and not self._task.done()

    async def wait_ready(self) -> None:
        await self._ready.wait()
        if self.client is None:
            raise self.error or RuntimeError(f"MCP 서버에 연결하지 못했습니다 ({self.config.name}).")

    async def close(self) -> None:
        self._stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(self._task), _CLOSE_TIMEOUT_SECONDS)
        except BaseException:
            self._task.cancel()


_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_start_lock = threading.Lock()
_connections: dict[tuple, _Connection] = {}  # 배경 루프 안에서만 만지므로 잠금이 필요 없다


def _key(config: MCPServerConfig) -> tuple:
    return (config.name, config.transport, config.url, config.command, tuple(config.args), config.cwd,
            tuple(sorted(config.env.items())))


def _serve(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _thread
    with _start_lock:
        if _loop is None or _thread is None or not _thread.is_alive():
            _connections.clear()  # 이전 루프에 묶인 연결은 쓸 수 없다
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=_serve, args=(loop,), name="mcp-client-loop", daemon=True)
            thread.start()
            _loop, _thread = loop, thread
        return _loop


async def _connection(config: MCPServerConfig) -> _Connection:
    key = _key(config)
    conn = _connections.get(key)
    if conn is not None and not conn.alive:
        _connections.pop(key, None)  # 서버가 죽었다
        conn = None
    if conn is None:
        conn = _Connection(config)
        _connections[key] = conn
    try:
        await conn.wait_ready()
    except BaseException:
        if _connections.get(key) is conn:
            del _connections[key]
        raise
    return conn


async def _discard(config: MCPServerConfig) -> None:
    conn = _connections.pop(_key(config), None)
    if conn is not None:
        await conn.close()


async def _use(config: MCPServerConfig, operation: Callable[[Any], Awaitable[Any]], timeout: float) -> Any:
    async def with_retry():
        for attempt in (1, 2):
            try:
                conn = await _connection(config)
                return await operation(conn.client)
            except NotImplementedError:
                raise
            except Exception:
                await _discard(config)  # 연결이 깨졌을 수 있으니 새로 만들어서 한 번 더 시도한다
                if attempt == 2:
                    raise

    try:
        return await asyncio.wait_for(with_retry(), timeout)
    except asyncio.TimeoutError:
        await _discard(config)  # 멈춘 서버일 수 있다
        raise


def run(config: MCPServerConfig, operation: Callable[[Any], Awaitable[Any]], timeout: float) -> Any:
    """operation(client)를 재사용하는 연결로 실행하고 결과를 돌려준다. 시간 초과면 TimeoutError."""
    loop = _ensure_loop()
    return asyncio.run_coroutine_threadsafe(_use(config, operation, timeout), loop).result()


async def _close_all() -> None:
    for key in list(_connections):
        conn = _connections.pop(key)
        await conn.close()


def close_all() -> None:
    """연결과 서버 프로세스를 모두 정리한다 (앱 종료 때 자동으로 부른다)."""
    loop, thread = _loop, _thread
    if loop is None or thread is None or not thread.is_alive():
        return
    try:
        asyncio.run_coroutine_threadsafe(_close_all(), loop).result(_CLOSE_TIMEOUT_SECONDS * 2)
    except Exception:
        pass
    finally:
        loop.call_soon_threadsafe(loop.stop)


atexit.register(close_all)
