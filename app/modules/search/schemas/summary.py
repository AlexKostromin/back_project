from __future__ import annotations

from pydantic import BaseModel, Field


class DecisionSummary(BaseModel):
    """Структурированное саммари судебного решения, сгенерированное LLM.

    Контракт стабилен: фронт LexInsight рендерит карточку решения
    из этих четырёх текстовых полей плюс ``key_norms`` для чипов
    с применёнными нормами. ``tokens_used`` — служебное поле
    аудита расхода LLM на demo-тарифе ``GIGACHAT_API_PERS``,
    оно показывается админу, но не пользователю.

    Поля:
    - ``summary`` — суть спора и итог суда (2–3 предложения).
    - ``key_norms`` — список применённых норм в человекочитаемом
      виде, например ``["ГК РФ ст. 506", "НК РФ ст. 252"]``.
    - ``parties_brief`` — одна строка вида "истец vs ответчик".
    - ``outcome`` — что именно постановил суд.
    - ``tokens_used`` — сумма prompt + completion tokens для аудита.
    """

    summary: str = Field(
        ...,
        description="Суть спора и итог суда, 2–3 предложения.",
    )
    key_norms: list[str] = Field(
        default_factory=list,
        description="Применённые нормы права, например 'ГК РФ ст. 506'.",
    )
    parties_brief: str = Field(
        ...,
        description="Стороны спора одной строкой: истец vs ответчик.",
    )
    outcome: str = Field(
        ...,
        description="Итог: что суд постановил/взыскал.",
    )
    tokens_used: int = Field(
        ...,
        ge=0,
        description="Сумма prompt + completion tokens, отданная LLM-провайдером.",
    )
