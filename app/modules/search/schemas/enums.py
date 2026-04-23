from __future__ import annotations

from enum import StrEnum


class SourceName(StrEnum):
    ARBITR = "arbitr"
    SUDRF = "sudrf"
    VSRF = "vsrf"
    KSRF = "ksrf"
    FAS = "fas"


class CourtType(StrEnum):
    ARBITRAZH = "arbitrazh"
    SOY = "soy"
    KS = "ks"
    VS = "vs"
    FAS = "fas"


class DocType(StrEnum):
    RESHENIE = "решение"
    POSTANOVLENIE = "постановление"
    OPREDELENIE = "определение"
    PRIGOVOR = "приговор"
    PISMO = "письмо"
    OSOBOE_MNENIE = "особое_мнение"


class DecisionResult(StrEnum):
    SATISFIED = "satisfied"
    PARTIAL = "partial"
    DENIED = "denied"
    RETURNED = "returned"
    OTHER = "other"


class AppealStatus(StrEnum):
    APPEALED = "appealed"
    OVERTURNED = "overturned"
    PARTIAL_OVERTURNED = "partial_overturned"
    UPHELD = "upheld"
    NONE = "none"


class DisputeType(StrEnum):
    ADMIN = "admin"
    BANKRUPTCY = "bankruptcy"
    CIVIL = "civil"
    CRIMINAL = "criminal"


class ParticipantRole(StrEnum):
    PLAINTIFF = "plaintiff"
    DEFENDANT = "defendant"
    THIRD_PARTY = "third_party"
    OTHER = "other"
