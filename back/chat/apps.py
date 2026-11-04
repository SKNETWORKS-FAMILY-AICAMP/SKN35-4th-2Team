import logging
import os
import sys

from django.apps import AppConfig

# 서버를 켜는 명령이 아닌 관리 명령에서는 미리 불러오기(웜업)를 하지 않는다
NO_WARM_UP_COMMANDS = {"migrate", "makemigrations", "check", "shell", "test", "collectstatic", "createsuperuser", "showmigrations"}


def should_warm_up(argv, environ):
    """서버 프로세스에서만 웜업한다. runserver 자동 재시작은 부모 프로세스에서는 건너뛴다(메모리를 두 번 쓰지 않게)."""
    if environ.get("CODECLUE_NO_WARMUP") == "1":
        return False
    command = argv[1] if len(argv) > 1 else ""
    if command in NO_WARM_UP_COMMANDS:
        return False
    if command == "runserver" and "--noreload" not in argv and environ.get("RUN_MAIN") != "true":
        return False
    return True


class ChatConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "chat"
    verbose_name = "CodeClue 채팅"

    def ready(self):
        from . import checks  # noqa: F401  (manage.py check에서 재정렬 모델 폴더를 확인하도록 등록)

        if should_warm_up(sys.argv, os.environ):
            problem = checks.reranker_problem()
            if problem:  # gunicorn으로 켤 때도 로그에 남긴다 (manage.py check는 gunicorn에서는 실행되지 않는다)
                logging.getLogger(__name__).warning("%s %s", problem, checks.RERANKER_HINT)

            from src.app.chat_service import warm_up

            warm_up()  # 별도 스레드에서 그래프, 재정렬 모델, 검색기를 미리 준비한다 (첫 질문 대기 단축)
