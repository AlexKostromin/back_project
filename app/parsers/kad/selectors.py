from __future__ import annotations

from datetime import date

import structlog
from bs4 import BeautifulSoup

from app.parsers.kad.schemas import DocumentRef, KadParty
from app.parsers.schemas import ParticipantRole

logger = structlog.get_logger(__name__)


def extract_case_id(soup: BeautifulSoup) -> str:
    """Extract case_id from hidden input#caseId."""
    input_elem = soup.find("input", id="caseId")
    if not input_elem or not input_elem.get("value"):
        logger.warning("kad.selector.case_id.not_found")
        raise ValueError("case_id not found in card")
    return str(input_elem["value"])


def extract_case_number(soup: BeautifulSoup) -> str:
    """Extract case_number from hidden input#caseName."""
    input_elem = soup.find("input", id="caseName")
    if not input_elem or not input_elem.get("value"):
        logger.warning("kad.selector.case_number.not_found")
        raise ValueError("case_number not found in card")
    return str(input_elem["value"])


def extract_court_name(soup: BeautifulSoup) -> str:
    """Extract court name from table header link in gr_case_judges section."""
    judges_section = soup.find("div", id="gr_case_judges")
    if judges_section:
        link = judges_section.find("a", href=True)
        if link and link.get_text(strip=True):
            return link.get_text(strip=True)

    logger.warning("kad.selector.court_name.not_found")
    raise ValueError("court_name not found in card")


def extract_instance_level(soup: BeautifulSoup) -> int:
    """Extract instance level from data-instance_level attribute."""
    span_elem = soup.find("span", class_="js-case-header-case_num")
    if span_elem and span_elem.get("data-instance_level"):
        try:
            level = int(span_elem["data-instance_level"])
            if 1 <= level <= 4:
                return level
        except (ValueError, TypeError):
            pass

    logger.warning("kad.selector.instance_level.not_found")
    raise ValueError("instance_level not found in card")


def extract_dispute_category(soup: BeautifulSoup) -> str | None:
    """Extract dispute category from h2 tag in case header."""
    h2_elem = soup.find("h2")
    if h2_elem:
        text = h2_elem.get_text(strip=True)
        if text:
            return text

    logger.warning("kad.selector.dispute_category.not_found")
    return None


def extract_parties(soup: BeautifulSoup) -> list[KadParty]:
    """Extract parties from b-case-info table.

    Columns: plaintiffs, defendants, third, others.
    Maps to ParticipantRole: PLAINTIFF, DEFENDANT, THIRD_PARTY, OTHER.
    """
    parties: list[KadParty] = []

    table = soup.find("table", class_="b-case-info")
    if not table:
        logger.warning("kad.selector.parties.table_not_found")
        return parties

    tbody = table.find("tbody")
    if not tbody:
        return parties

    tr = tbody.find("tr")
    if not tr:
        return parties

    role_mapping = {
        "plaintiffs": ParticipantRole.PLAINTIFF,
        "defendants": ParticipantRole.DEFENDANT,
        "third": ParticipantRole.THIRD_PARTY,
        "others": ParticipantRole.OTHER,
    }

    for td in tr.find_all("td", recursive=False):
        role = None
        for class_name, participant_role in role_mapping.items():
            if class_name in td.get("class", []):
                role = participant_role
                break

        if role is None:
            continue

        lis = td.find_all("li")
        for li in lis:
            link = li.find("a")
            if not link:
                continue

            name = link.get_text(strip=True)
            if not name:
                continue

            rollover = li.find("span", class_="js-rolloverHtml")
            address = None
            if rollover:
                address_text = rollover.get_text(strip=True)
                if address_text:
                    address = address_text

            parties.append(
                KadParty(
                    name=name,
                    role=role,
                    inn=None,
                    ogrn=None,
                    address=address,
                )
            )

    return parties


def extract_judges(soup: BeautifulSoup) -> list[str]:
    """Extract judges from gr_case_judges section."""
    judges: list[str] = []

    judges_section = soup.find("div", id="gr_case_judges")
    if not judges_section:
        logger.warning("kad.selector.judges.section_not_found")
        return judges

    tbody = judges_section.find("tbody")
    if not tbody:
        return judges

    lis = tbody.find_all("li")
    for li in lis:
        judge_name = li.get_text(strip=True)
        if judge_name:
            judges.append(judge_name)

    return judges


def extract_document_refs(soup: BeautifulSoup) -> list[DocumentRef]:
    """Extract document references from case chronology.

    Note: В статичной фикстуре chrono_ed_content пустой (загружается динамически).
    Этот селектор вернёт пустой список для такой фикстуры.
    Полноценный парсинг документов будет реализован в Stage 3d.
    """
    logger.debug("kad.selector.document_refs.not_implemented_yet")
    return []
