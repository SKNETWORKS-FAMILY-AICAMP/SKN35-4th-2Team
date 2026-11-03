"""
비밀번호 해시 / 검증 (표준 라이브러리 hashlib.scrypt 사용).

- 비밀번호 원문은 어디에도 저장하지 않고, 사용자마다 다른 salt를 섞어 해시만 저장한다.
- 저장 형식: scrypt$N$r$p$salt(base64)$hash(base64)
  파라미터를 같이 적어 두면 나중에 강도를 올려도 기존 해시를 계속 검증할 수 있다.
- 비교는 hmac.compare_digest로 한다 (일치하는 앞부분 길이로 정답을 추측하는 공격 방지).
- argon2 같은 전용 라이브러리가 더 흔하지만 의존성이 늘어서, 표준 라이브러리로 시작한다.
"""

import base64
import hashlib
import hmac
import os

# 메모리 약 16MB, 한 번 해시에 수십 ms 수준. 시연 PC 부담이 크지 않은 중간 강도.
_N, _R, _P = 2**14, 8, 1
_SALT_BYTES = 16
_DKLEN = 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("비밀번호가 비어 있습니다.")
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN
    )
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """형식이 깨졌거나 비밀번호가 틀리면 예외 없이 False."""
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)
