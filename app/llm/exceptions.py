from __future__ import annotations

from app.core.exceptions import AppError


class LLMError(AppError):
    """Базовая ошибка LLM-провайдера.

    Все внешние сбои GigaChat/любого другого LLM-адаптера должны
    разворачиваться в подкласс ``LLMError`` — это даёт стабильный
    контракт для error-handler'ов, не протекая исключениями httpx
    или json в верхние слои.

    По умолчанию рендерится как ``502 Bad Gateway``: для клиента
    LexInsight LLM — это внешняя зависимость, и её отказ не есть
    "клиентская" ошибка в смысле 4xx.
    """

    code = "llm_error"
    status_code = 502
    detail = "LLM provider error"


class LLMAuthError(LLMError):
    """Авторизация в LLM-провайдере не удалась после попытки refresh.

    Сюда же попадает повторный 401 после ретрая с новым токеном —
    значит, проблема не в просрочке, а в самих credentials/scope.
    Имя/значение секретов в ``detail`` НЕ попадают.
    """

    code = "llm_auth_error"
    status_code = 502
    detail = "LLM authentication failed"


class LLMRateLimitError(LLMError):
    """Провайдер ответил 429 / ограничил доступ по месячному лимиту.

    На demo-тарифе ``GIGACHAT_API_PERS`` это типичный финал жизни
    токенов и не повод ронять процесс — клиент видит 503 и
    может повторить позже.
    """

    code = "llm_rate_limited"
    status_code = 503
    detail = "LLM rate limit exceeded"


class LLMTimeoutError(LLMError):
    """httpx превысил настроенный ``gigachat_request_timeout_s``.

    Маппится в ``504 Gateway Timeout`` — это семантически точнее, чем
    502: соединение установилось, провайдер просто не успел ответить.
    """

    code = "llm_timeout"
    status_code = 504
    detail = "LLM provider timed out"


class LLMResponseError(LLMError):
    """Контракт ответа провайдера нарушен: невалидный JSON, отсутствуют
    обязательные поля, или ``DecisionSummary`` не валидируется.

    Отдельный класс нужен, чтобы отличать "LLM физически ответил, но
    мы не понимаем что" от auth/rate/timeout — это разные incident-ы
    в проде и разные дашборды.
    """

    code = "llm_response_invalid"
    status_code = 502
    detail = "LLM returned an invalid response"
