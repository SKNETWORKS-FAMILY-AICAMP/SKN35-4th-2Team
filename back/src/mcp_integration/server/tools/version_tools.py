"""
버전 도구 두 개 (PyPI 공개 API, 키 필요 없음).

- get_latest_version   : 패키지의 최신 정식 버전과 출시일
- check_version_compat : 사용자가 쓰는 패키지들의 버전이 서로 맞는지 계산

라이브러리 버전은 GitHub 릴리스가 아니라 PyPI를 기준으로 한다.
langchain, langgraph 저장소는 한 저장소에 패키지가 여러 개라서 GitHub의 "최신 릴리스"가 다른 하위 패키지의 것일 수 있다
(2026-10 확인: langgraph 저장소의 최신 릴리스가 'cli==0.4.33', langchain 저장소는 'langchain-core==1.6.9'로 나왔다).

순수 함수(latest_version, check_compat)와 도구 등록(register)을 나눠서 시험하기 쉽게 했다.
"""

import asyncio
import re
from urllib.parse import quote

from mcp.server.mcpserver.exceptions import ToolError
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from src.const import mcp_config as cfg
from src.mcp_integration.server.tools import common

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:==|\s)\s*([0-9][A-Za-z0-9.+!_-]*)")
_PY = re.compile(r"\d+\.\d+(?:\.\d+)?")
_LINK_KEYS = ("Changelog", "Source", "Documentation", "Homepage")


def _pypi_url(name: str, version: str | None = None) -> str:
    base = f"https://pypi.org/pypi/{quote(name)}"
    return f"{base}/{quote(version)}/json" if version else f"{base}/json"


def _check_name(package: str) -> str:
    name = (package or "").strip()
    if not _NAME.fullmatch(name):
        raise ToolError(f"'{package}'는 올바른 패키지 이름이 아닙니다 (예: langgraph).")
    return name


def _upload_time(files: list[dict]) -> str | None:
    times = [f["upload_time_iso_8601"] for f in files if f.get("upload_time_iso_8601")]
    return min(times) if times else None


def _stable_versions(releases: dict) -> list[tuple[Version, str | None]]:
    """(버전, 출시 시각) 목록. 시험판과 전부 철회된(yanked) 버전은 뺀다. 최신순."""
    found = []
    for text, files in releases.items():
        try:
            version = Version(text)
        except InvalidVersion:
            continue
        if version.is_prerelease or not files or all(f.get("yanked") for f in files):
            continue
        found.append((version, _upload_time(files)))
    return sorted(found, key=lambda item: item[0], reverse=True)


# ---------------------------------------------------------------- 최신 버전 조회
async def latest_version(package: str) -> dict:
    name = _check_name(package)
    data = await common.fetch_json(_pypi_url(name), what="PyPI")
    info = data["info"]
    releases = data.get("releases") or {}
    stable = _stable_versions(releases)
    if stable:
        version, released_at = str(stable[0][0]), stable[0][1]
    else:  # 정식 버전이 하나도 없는 패키지(시험판만 있음)
        version = info["version"]
        released_at = _upload_time(releases.get(version) or data.get("urls") or [])
    return {
        "package": info.get("name") or name,
        "latest_version": version,
        "released_at": released_at,
        "requires_python": info.get("requires_python"),
        "summary": info.get("summary"),
        "recent_versions": [
            {"version": str(v), "released_at": at} for v, at in stable[: cfg.VERSION_RECENT_COUNT]
        ],
        "links": {k: v for k, v in (info.get("project_urls") or {}).items() if k in _LINK_KEYS},
        "source": "PyPI",
        "url": f"https://pypi.org/project/{quote(name)}/",
        "retrieved_at": common.now_iso(),
        "note": "PyPI의 최신 정식 버전입니다 (시험판 제외).",
    }


# ---------------------------------------------------------------- 호환성 점검
def parse_pins(packages: list[str]) -> dict[str, str]:
    """["langchain==1.4.0", ...] -> {"langchain": "1.4.0"} (이름은 PyPI 표준 형태로 바꾼다)"""
    if not isinstance(packages, list) or not packages:
        raise ToolError("packages는 비어 있지 않은 목록이어야 합니다 (예: ['langchain==1.4.0', 'langgraph==0.2.0']).")
    if len(packages) > cfg.COMPAT_MAX_PACKAGES:
        raise ToolError(f"한 번에 {cfg.COMPAT_MAX_PACKAGES}개까지만 점검할 수 있습니다 (받은 개수: {len(packages)}).")
    pins: dict[str, str] = {}
    for raw in packages:
        match = _PIN.fullmatch(str(raw).strip())
        if not match:
            raise ToolError(f"'{raw}'는 '패키지==버전' 형태가 아닙니다 (예: langchain==1.4.0).")
        name, text = canonicalize_name(match.group(1)), match.group(2)
        try:
            Version(text)
        except InvalidVersion as exc:
            raise ToolError(f"'{raw}'의 버전 '{text}'이(가) 올바르지 않습니다.") from exc
        if pins.setdefault(name, text) != text:
            raise ToolError(f"'{name}'이(가) 서로 다른 버전으로 두 번 들어 있습니다.")
    return pins


def _marker_env(python_version: str) -> dict[str, str]:
    if not python_version:
        return {"extra": ""}
    v = Version(python_version)
    return {
        "python_version": f"{v.major}.{v.minor}",
        "python_full_version": f"{v.major}.{v.minor}.{v.micro}",
        "extra": "",
    }


def _requirements(info: dict, env: dict[str, str]) -> list[Requirement]:
    """그 버전이 요구하는 다른 패키지들 (extra 전용이거나 이 Python에는 해당 없는 조건은 뺀다)."""
    found = []
    for text in info.get("requires_dist") or []:
        try:
            req = Requirement(text)
        except InvalidRequirement:
            continue
        if req.marker is not None and not req.marker.evaluate(env):
            continue
        found.append(req)
    return found


async def _suggest(name: str, specs: list[SpecifierSet]) -> str | None:
    """name의 버전 중 모든 조건(specs)을 만족하는 가장 높은 정식 버전."""
    data = await common.fetch_json(_pypi_url(name), what="PyPI")
    for version, _ in _stable_versions(data.get("releases") or {}):
        if all(spec.contains(version, prereleases=False) for spec in specs):
            return str(version)
    return None


async def check_compat(packages: list[str], python_version: str = "") -> dict:
    pins = parse_pins(packages)
    python_version = (python_version or "").strip()
    if python_version and not _PY.fullmatch(python_version):
        raise ToolError(f"python_version '{python_version}'은 '3.12' 또는 '3.12.4' 형태여야 합니다.")
    env = _marker_env(python_version)

    names = list(pins)
    results = await asyncio.gather(
        *(common.fetch_json(_pypi_url(n, pins[n]), what="PyPI") for n in names), return_exceptions=True
    )
    infos: dict[str, dict] = {}
    unresolved = []
    for name, result in zip(names, results):
        if isinstance(result, ToolError):
            unresolved.append({"package": f"{name}=={pins[name]}", "reason": str(result)})
        elif isinstance(result, BaseException):
            raise result
        else:
            infos[name] = result["info"]
    if not infos:
        raise ToolError("입력한 패키지를 하나도 PyPI에서 확인하지 못했습니다. " + "; ".join(u["reason"] for u in unresolved))

    conflicts, python_problems = [], []
    needs: dict[str, list[tuple[str, SpecifierSet]]] = {}  # 충돌한 패키지 -> (요구한 쪽, 조건)
    for name, info in infos.items():
        declared_by = f"{name}=={pins[name]}"
        if python_version and info.get("requires_python"):
            try:
                ok = SpecifierSet(info["requires_python"]).contains(Version(python_version), prereleases=True)
            except InvalidSpecifier:
                ok = True
            if not ok:
                python_problems.append(
                    {"package": declared_by, "requires_python": info["requires_python"], "python_version": python_version}
                )
        for req in _requirements(info, env):
            dep = canonicalize_name(req.name)
            if dep not in pins or dep == name:
                continue
            if not req.specifier.contains(Version(pins[dep]), prereleases=True):
                conflicts.append(
                    {
                        "package": f"{dep}=={pins[dep]}",
                        "required_by": declared_by,
                        "requirement": f"{req.name}{req.specifier}",
                    }
                )
                needs.setdefault(dep, []).append((declared_by, req.specifier))

    suggestions = []
    for dep, wanted in needs.items():
        suggestions.append(
            {
                "package": dep,
                "installed": pins[dep],
                "suggested_version": await _suggest(dep, [spec for _, spec in wanted]),
                "satisfies": [f"{by}: {spec}" for by, spec in wanted],
            }
        )

    return {
        "compatible": not conflicts and not python_problems,
        "checked_packages": [f"{n}=={pins[n]}" for n in infos],
        "python_version": python_version or None,
        "python_problems": python_problems,
        "conflicts": conflicts,
        "suggestions": suggestions,
        "unresolved": unresolved,
        "sources": [f"https://pypi.org/project/{quote(n)}/{quote(pins[n])}/" for n in infos],
        "retrieved_at": common.now_iso(),
        "note": "입력한 패키지들 사이의 직접 의존 조건만 확인합니다. 목록에 없는 패키지나 간접 의존성은 확인하지 않습니다. "
        "suggested_version이 null이면 입력한 패키지들의 조건을 모두 만족하는 정식 버전을 찾지 못한 것입니다.",
    }


# ---------------------------------------------------------------- 도구 등록
def register(mcp) -> None:
    @mcp.tool()
    async def get_latest_version(package: str) -> str:
        """PyPI에서 파이썬 패키지의 최신 정식 버전, 출시일, 지원 Python 버전, 최근 버전 목록을 조회한다.

        라이브러리(langchain, langgraph, mcp 등)의 "최신 버전"이나 "언제 나왔나"를 물을 때 쓴다.
        GitHub 저장소의 릴리스는 한 저장소에 패키지가 여러 개 있어 다른 패키지의 릴리스가 나올 수 있으므로, 버전은 이 도구로 확인한다.
        알려 주는 것은 버전 번호, 출시일, 지원 Python 버전, 변경 기록 링크뿐이다. 버전 사이에 무엇이 바뀌었는지(변경 내용,
        마이그레이션 방법)는 알려 주지 않으므로, 그런 질문에는 쓰지 않는다.

        Args:
            package: PyPI 패키지 이름. LangChain 계열이 아니어도 조회할 수 있다 (예: langgraph, langchain, mcp, langchain-openai, pydantic)
        """
        return common.dump(await latest_version(package))

    @mcp.tool()
    async def check_version_compat(packages: list[str], python_version: str = "") -> str:
        """사용자가 쓰는 패키지들의 버전이 서로 맞는지 계산해서 충돌과 맞는 버전을 알려 준다.

        "A와 B를 같이 써도 되나", "업그레이드했더니 ImportError가 난다", "No matching distribution" 같은
        버전 불일치가 의심될 때 쓴다. 각 패키지가 PyPI에 선언한 의존 조건(예: langgraph>=1.2.11)과 지원 Python 버전을
        사용자의 버전과 비교한다. 입력한 패키지들 사이의 직접 조건만 확인한다.

        Args:
            packages: '패키지==버전' 목록 (예: ["langchain==1.4.0", "langgraph==0.2.0"]). 최대 10개.
                사용자가 말한 버전만 넣는다. 버전을 말하지 않은 패키지의 버전을 추측해서 넣지 않는다
            python_version: 사용자의 Python 버전 (예: "3.12"). 모르면 비워 둔다
        """
        return common.dump(await check_compat(packages, python_version))
