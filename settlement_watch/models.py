from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    text = str(value).strip()
    return [text] if text else []


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(text[:26].replace("Z", ""), fmt.replace("Z", "")).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


@dataclass(frozen=True)
class WatchTarget:
    name: str
    entity_type: str = "unknown"
    aliases: tuple[str, ...] = ()
    notes: str = ""

    def query_names(self) -> list[str]:
        names = [self.name, *self.aliases]
        seen: set[str] = set()
        out: list[str] = []
        for name in names:
            cleaned = " ".join(name.split())
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                out.append(cleaned)
        return out


@dataclass
class DocketRecord:
    docket_id: str
    case_name: str
    court: str
    court_id: str
    docket_number: str
    date_filed: date | None
    date_terminated: date | None
    cause: str
    suit_nature: str
    jurisdiction: str
    assigned_to: str
    pacer_case_id: str
    url: str
    parties: list[str] = field(default_factory=list)
    attorneys: list[str] = field(default_factory=list)
    document_texts: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> DocketRecord:
        docs = payload.get("recap_documents") or payload.get("recapDocuments") or []
        texts: list[str] = []
        if isinstance(docs, list):
            for doc in docs:
                if not isinstance(doc, dict):
                    texts.append(str(doc))
                    continue
                for key in ("description", "snippet", "plain_text", "plainText"):
                    value = doc.get(key)
                    if value:
                        texts.append(str(value))
        url_path = (
            payload.get("docket_absolute_url")
            or payload.get("absolute_url")
            or payload.get("absoluteUrl")
            or ""
        )
        url = str(url_path)
        if url and url.startswith("/"):
            url = "https://www.courtlistener.com" + url

        docket_id = payload.get("docket_id") or payload.get("id") or ""
        return cls(
            docket_id=str(docket_id),
            case_name=str(payload.get("caseName") or payload.get("case_name") or ""),
            court=str(payload.get("court") or ""),
            court_id=str(payload.get("court_id") or payload.get("courtId") or ""),
            docket_number=str(
                payload.get("docketNumber") or payload.get("docket_number") or ""
            ),
            date_filed=_parse_date(payload.get("dateFiled") or payload.get("date_filed")),
            date_terminated=_parse_date(
                payload.get("dateTerminated") or payload.get("date_terminated")
            ),
            cause=str(payload.get("cause") or ""),
            suit_nature=str(
                payload.get("suitNature")
                or payload.get("nature_of_suit")
                or payload.get("natureOfSuit")
                or ""
            ),
            jurisdiction=str(
                payload.get("jurisdictionType") or payload.get("jurisdiction") or ""
            ),
            assigned_to=str(
                payload.get("assignedTo") or payload.get("assigned_to") or ""
            ),
            pacer_case_id=str(
                payload.get("pacer_case_id") or payload.get("pacerCaseId") or ""
            ),
            url=url,
            parties=_as_list(payload.get("party") or payload.get("parties")),
            attorneys=_as_list(payload.get("attorney") or payload.get("attorneys")),
            document_texts=texts,
        )

    def combined_text(self) -> str:
        parts = [
            self.case_name,
            self.cause,
            self.suit_nature,
            " ".join(self.parties),
            " ".join(self.document_texts),
        ]
        return "\n".join(part for part in parts if part)

    def days_open(self) -> int | None:
        if self.date_filed is None or self.date_terminated is None:
            return None
        return (self.date_terminated - self.date_filed).days


@dataclass(frozen=True)
class Flag:
    code: str
    title: str
    detail: str
    weight: int


@dataclass
class ScoredCase:
    watch_name: str
    entity_type: str
    docket: DocketRecord
    flags: list[Flag]
    amounts: list[int]
    settlement_indicated: bool
    risk_score: int
    risk_band: str
    review_priority: str

    @property
    def flag_codes(self) -> str:
        return "; ".join(flag.code for flag in self.flags)

    @property
    def flag_details(self) -> str:
        return " | ".join(f"{flag.code}: {flag.detail}" for flag in self.flags)
