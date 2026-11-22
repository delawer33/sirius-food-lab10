"""
Сквозной тест API для обоих бэкендов хранилища.

Весь вывод scripts/smoke.py должен совпасть с docs/smoke_lab3.txt, а строки
[mvp] — с ответами MVP-версии из docs/smoke_mvp.txt: для авторизованного
пользователя структура и тексты ответов не изменились.
"""
from pathlib import Path

from app.core import config
from scripts.smoke import PASSWORD, run

DOCS = Path(__file__).resolve().parents[2] / "docs"
EXPECTED = (DOCS / "smoke_lab3.txt").read_text(encoding="utf-8").splitlines()
MVP = (DOCS / "smoke_mvp.txt").read_text(encoding="utf-8").splitlines()

# Строка MVP «заказ от user_id=999 -> 404 Пользователь не найден». Такой
# запрос больше невозможен: user_id берётся из токена, а токен выдаётся
# только существующему пользователю.
REMOVED_MVP_LINES = {21}


def answers(lines: list[str]) -> list[str]:
    return [line.rsplit(" -> ", 1)[1] for line in lines]


def test_api_matches_expected_output(api, monkeypatch):
    # Скрипт логинится много раз подряд; лимит проверяется в test_security.
    monkeypatch.setattr(config.settings, "RATE_LIMIT_ENABLED", False)

    lines = run(api.client, lambda email, role: api.create_user(email, role, password=PASSWORD))

    assert lines == EXPECTED


def test_mvp_scenarios_answer_as_before():
    mvp_now = [line for line in EXPECTED if line.startswith("[mvp] ")]
    mvp_before = [line for i, line in enumerate(MVP) if i not in REMOVED_MVP_LINES]
    assert answers(mvp_now) == answers(mvp_before)
