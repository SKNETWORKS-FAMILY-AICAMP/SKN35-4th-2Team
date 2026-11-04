from django.urls import path

from . import accounts, conversations, views

app_name = "chat"

urlpatterns = [
    path("", views.index, name="index"),  # 채팅 화면 (front/templates/chat.html)
    path("api/chat/", views.chat_stream, name="chat_stream"),  # 질문 -> 스트리밍 답변
    path("api/auth/signup/", accounts.signup, name="signup"),
    path("api/auth/login/", accounts.login, name="login"),
    path("api/auth/captcha/", accounts.login_captcha, name="login_captcha"),
    path("auth/lockout/", accounts.lockout, name="lockout"),
    path("api/auth/logout/", accounts.logout, name="logout"),
    path("api/auth/me/", accounts.me, name="me"),
    path("api/conversations/", conversations.conversation_list, name="conversation_list"),
    path("api/conversations/<int:conversation_id>/", conversations.conversation_detail, name="conversation_detail"),
    path("api/conversations/<int:conversation_id>/pin/", conversations.conversation_pin, name="conversation_pin"),
    path("api/attachments/<int:attachment_id>/", conversations.attachment, name="attachment"),
    path("api/health/", views.health, name="health"),  # 배포 확인용
]
