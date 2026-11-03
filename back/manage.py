#!/usr/bin/env python
"""Django 관리 명령 진입점. 이 파일이 back/ 안에 있어서 back/src(3차 코어)를 `import src...`로 바로 불러올 수 있다.

    uv run python back/manage.py runserver      # 개발 서버
    uv run python back/manage.py test chat      # 시험
"""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("Django를 불러오지 못했습니다. 프로젝트 폴더에서 `uv sync`를 먼저 실행했는지 확인하세요.") from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
