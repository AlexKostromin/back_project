from __future__ import annotations


class AppError(Exception):
    """Base class for all domain errors rendered as structured JSON by the API.

    Subclasses set ``code``, ``status_code``, and ``detail`` as class attributes.
    ``field`` is optional and used for field-level validation errors.
    """

    code: str = "app_error"
    status_code: int = 500
    detail: str = "Application error"
    field: str | None = None

    def __init__(
        self,
        detail: str | None = None,
        *,
        field: str | None = None,
    ) -> None:
        if detail is not None:
            self.detail = detail
        if field is not None:
            self.field = field
        super().__init__(self.detail)


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404
    detail = "Resource not found"
