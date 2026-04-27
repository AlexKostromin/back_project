from __future__ import annotations

import uuid

import structlog

from app.parsers.kad.dates import aspnet_date_to_msk_date
from app.parsers.kad.schemas import DocumentRef

logger = structlog.get_logger(__name__)

MAX_ITEMS_PER_RESPONSE = 1000  # DoS protection cap


def parse_chronology_response(payload: dict) -> list[DocumentRef]:
    """Parse CaseDocumentsPage AJAX response to list of DocumentRef.

    Filters:
        - IsAct must be true (судебные акты only)
        - IsDeleted must be false

    Args:
        payload: Parsed JSON response from /Kad/CaseDocumentsPage

    Returns:
        List of DocumentRef objects

    Raises:
        ValueError: If payload is invalid (Success != True or missing Result.Items)

    Examples:
        >>> payload = {"Success": True, "Result": {"Items": [...]}}
        >>> refs = parse_chronology_response(payload)
    """
    if not payload.get("Success"):
        raise ValueError(
            "Invalid CaseDocumentsPage response: Success != True"
        )

    result = payload.get("Result")
    if not result or "Items" not in result:
        raise ValueError(
            "Invalid CaseDocumentsPage response: missing Result.Items"
        )

    items = result["Items"]
    if not isinstance(items, list):
        raise ValueError(
            "Invalid CaseDocumentsPage response: Result.Items is not a list"
        )

    if len(items) > MAX_ITEMS_PER_RESPONSE:
        raise ValueError(
            f"Too many items in response: {len(items)} > {MAX_ITEMS_PER_RESPONSE}"
        )

    refs: list[DocumentRef] = []

    for item in items:
        # Apply filters
        if not item.get("IsAct"):
            logger.debug(
                "kad.chronology.skip_non_act",
                document_id=item.get("Id"),
                document_type=item.get("DocumentTypeName"),
            )
            continue

        if item.get("IsDeleted"):
            logger.debug(
                "kad.chronology.skip_deleted",
                document_id=item.get("Id"),
                document_type=item.get("DocumentTypeName"),
            )
            continue

        # Extract required fields
        document_id = item.get("Id")
        if not document_id:
            logger.warning(
                "kad.chronology.missing_id",
                document_type=item.get("DocumentTypeName"),
            )
            continue

        date_str = item.get("Date")
        if not date_str:
            logger.warning(
                "kad.chronology.missing_date",
                document_id=document_id,
            )
            continue

        try:
            document_date = aspnet_date_to_msk_date(date_str)
        except ValueError as e:
            logger.warning(
                "kad.chronology.invalid_date",
                document_id=document_id,
                date_str=date_str,
                error=str(e),
            )
            continue

        case_id = item.get("CaseId")
        if not case_id:
            logger.warning(
                "kad.chronology.missing_case_id",
                document_id=document_id,
            )
            continue

        file_name = item.get("FileName")
        if not file_name:
            logger.warning(
                "kad.chronology.missing_filename",
                document_id=document_id,
            )
            continue

        # Build PDF URL
        try:
            url = build_pdf_url(
                case_id=case_id,
                document_id=document_id,
                file_name=file_name,
                is_simple_justice=item.get("IsSimpleJustice", False),
            )
        except ValueError as e:
            logger.warning(
                "kad.chronology.invalid_url",
                document_id=document_id,
                error=str(e),
            )
            continue

        # Extract optional fields
        document_type = item.get("DocumentTypeName")
        content_types = item.get("ContentTypes", [])
        description = content_types[0] if content_types else None

        refs.append(
            DocumentRef(
                document_id=document_id,
                document_date=document_date,
                document_type=document_type,
                url=url,
                description=description,
            )
        )

    return refs


def build_pdf_url(
    *,
    case_id: str,
    document_id: str,
    file_name: str,
    is_simple_justice: bool,
) -> str:
    """Build PDF download URL for a KAD document.

    Args:
        case_id: Case UUID
        document_id: Document UUID
        file_name: PDF file name from response
        is_simple_justice: Whether document is from SimpleJustice subsystem

    Returns:
        Full PDF URL

    Raises:
        ValueError: If case_id, document_id, or file_name is empty

    Examples:
        >>> build_pdf_url(
        ...     case_id="abc",
        ...     document_id="def",
        ...     file_name="test.pdf",
        ...     is_simple_justice=False
        ... )
        'https://kad.arbitr.ru/Kad/PdfDocument/abc/def/test.pdf'
    """
    if not case_id:
        raise ValueError("case_id cannot be empty")
    if not document_id:
        raise ValueError("document_id cannot be empty")
    if not file_name:
        raise ValueError("file_name cannot be empty")

    # Validate case_id is a valid UUID (prevents path traversal)
    try:
        uuid.UUID(case_id)
    except ValueError as e:
        raise ValueError(f"case_id must be a valid UUID, got: {case_id!r}") from e

    # Validate document_id is a valid UUID (prevents path traversal)
    try:
        uuid.UUID(document_id)
    except ValueError as e:
        raise ValueError(f"document_id must be a valid UUID, got: {document_id!r}") from e

    # Validate file_name against path traversal and query injection
    if len(file_name) > 255:
        raise ValueError(f"file_name too long: {len(file_name)} > 255")
    if "/" in file_name or "\\" in file_name:
        raise ValueError("file_name must not contain path separators")
    if ".." in file_name:
        raise ValueError("file_name must not contain '..'")
    if "?" in file_name or "#" in file_name:
        raise ValueError("file_name must not contain query/fragment chars")
    if not file_name.lower().endswith(".pdf"):
        raise ValueError(f"file_name must end with .pdf, got: {file_name!r}")

    prefix = "SimpleJustice" if is_simple_justice else "Kad"
    return f"https://kad.arbitr.ru/{prefix}/PdfDocument/{case_id}/{document_id}/{file_name}"
