from __future__ import annotations

import re
from collections import defaultdict

from settlement_watch.models import DocketRecord, Flag, ScoredCase, WatchTarget

AMOUNT_RE = re.compile(
    r"\$\s*(\d{1,3}(?:,\d{3}){1,}|\d{4,})(?:\.\d{2})?"
)
TOKEN_RE = re.compile(r"[^a-z0-9]+")

SETTLEMENT_PATTERNS = (
    r"\bsettlement\b",
    r"\bsettled\b",
    r"stipulation of dismissal",
    r"stipulated dismissal",
    r"consent (?:judgment|decree|order)",
    r"compromise and settlement",
    r"notice of settlement",
    r"joint stipulation",
    r"rule 68",
    r"dismissal with prejudice",
)

SEALED_PATTERNS = (
    r"\bsealed\b",
    r"\bconfidential\b",
    r"in camera",
    r"under seal",
)

INJURY_PATTERNS = (
    r"personal physical injury",
    r"physical sickness",
    r"physical injury",
    r"irc\s*§?\s*104",
    r"104\(a\)\(2\)",
    r"pain and suffering",
    r"emotional distress damages",
    r"characterized as (?:personal )?injury",
)

BUSINESS_PATTERNS = (
    r"\bcontract\b",
    r"\bbreach\b",
    r"goods sold",
    r"unpaid invoices",
    r"account stated",
    r"\binsurance\b",
    r"\bfraud\b",
    r"\bcommercial\b",
    r"nature of suit:\s*contract",
)

STRUCTURED_PATTERNS = (
    r"structured settlement",
    r"\bannuity\b",
    r"periodic payments",
)

ASSIGNMENT_PATTERNS = (
    r"assignment of (?:settlement )?proceeds",
    r"assignment of the settlement",
    r"factor(?:ed|ing) settlement",
)

CONSENT_PATTERNS = (r"consent (?:judgment|decree|order)",)
DEFAULT_PATTERNS = (r"default judgment", r"entry of default")
STIPULATED_PATTERNS = (
    r"stipulation of dismissal",
    r"stipulated dismissal",
    r"joint stipulation",
)

RAPID_DAYS = 45
MIN_ROUND_AMOUNT = 10_000


def normalize(text: str) -> str:
    return TOKEN_RE.sub(" ", text.lower()).strip()


def _search_any(text: str, patterns: tuple[str, ...]) -> re.Match[str] | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match
    return None


def extract_amounts(text: str) -> list[int]:
    amounts: list[int] = []
    for match in AMOUNT_RE.finditer(text):
        raw = match.group(1).replace(",", "")
        try:
            value = int(raw)
        except ValueError:
            continue
        if value >= 1_000:
            amounts.append(value)
    return amounts


ENTITY_STOPWORDS = {
    "llc",
    "inc",
    "corp",
    "co",
    "ltd",
    "lp",
    "llp",
    "pllc",
    "na",
    "the",
    "company",
    "companies",
    "incorporated",
}


def _significant_tokens(name: str) -> list[str]:
    cleaned = name.replace(",", " ")
    return [
        token
        for token in normalize(cleaned).split()
        if token not in ENTITY_STOPWORDS and len(token) > 1
    ]


def shared_surname(docket: DocketRecord) -> str | None:
    case = docket.case_name
    split = re.split(r"\s+v\.?\s+", case, maxsplit=1, flags=re.IGNORECASE)
    if len(split) == 2:
        left, right = split[0], split[1]
    elif len(docket.parties) >= 2:
        left, right = docket.parties[0], docket.parties[1]
    else:
        return None

    left_tokens = _significant_tokens(left)
    right_tokens = _significant_tokens(right)
    if not left_tokens or not right_tokens:
        return None
    if left_tokens[-1] == right_tokens[-1]:
        return left_tokens[-1]
    prefix: list[str] = []
    for a, b in zip(left_tokens, right_tokens):
        if a == b:
            prefix.append(a)
        else:
            break
    if len(prefix) >= 2:
        return " ".join(prefix)
    overlap = set(left_tokens) & set(right_tokens)
    if len(overlap) >= 2:
        return " ".join(sorted(overlap))
    return None


def name_appears(target: WatchTarget, docket: DocketRecord) -> bool:
    haystack = normalize(
        " ".join([docket.case_name, *docket.parties, *docket.document_texts])
    )
    for query in target.query_names():
        tokens = normalize(query).split()
        if not tokens:
            continue
        if all(token in haystack.split() or token in haystack for token in tokens):
            return True
    return False


def score_docket(target: WatchTarget, docket: DocketRecord) -> ScoredCase:
    text = docket.combined_text()
    flags: list[Flag] = []
    amounts = extract_amounts(text)
    settlement_hit = _search_any(text, SETTLEMENT_PATTERNS)
    terminated = docket.date_terminated is not None
    settlement_indicated = bool(settlement_hit) or terminated

    if settlement_hit:
        flags.append(
            Flag(
                code="SETTLEMENT_INDICATED",
                title="Settlement language on public docket",
                detail=f"Matched “{settlement_hit.group(0)}”.",
                weight=5,
            )
        )
    elif terminated:
        flags.append(
            Flag(
                code="SETTLEMENT_INDICATED",
                title="Case terminated",
                detail="Docket is terminated; public record may reflect a settlement, judgment, or other disposition.",
                weight=3,
            )
        )

    days = docket.days_open()
    if days is not None and days <= RAPID_DAYS and settlement_indicated:
        flags.append(
            Flag(
                code="RAPID_RESOLUTION",
                title="Resolved shortly after filing",
                detail=f"Filed to termination in {days} day(s) (threshold {RAPID_DAYS}). Short, uncontested resolutions can be a collusive-suit indicator and need human review.",
                weight=20,
            )
        )

    consent = _search_any(text, CONSENT_PATTERNS)
    if consent:
        flags.append(
            Flag(
                code="CONSENT_JUDGMENT",
                title="Consent judgment / decree",
                detail=f"Matched “{consent.group(0)}”. Consent judgments are sometimes used to paper a transfer.",
                weight=15,
            )
        )

    default = _search_any(text, DEFAULT_PATTERNS)
    if default:
        flags.append(
            Flag(
                code="DEFAULT_JUDGMENT",
                title="Default judgment language",
                detail=f"Matched “{default.group(0)}”. Unopposed large judgments can be used to create collectible “debt.”",
                weight=12,
            )
        )

    sealed = _search_any(text, SEALED_PATTERNS)
    if sealed and settlement_indicated:
        flags.append(
            Flag(
                code="SEALED_OR_CONFIDENTIAL",
                title="Confidential or sealed resolution",
                detail=f"Matched “{sealed.group(0)}”. Confidentiality is common and lawful; it also hides characterization and related-party facts.",
                weight=10,
            )
        )

    stipulated = _search_any(text, STIPULATED_PATTERNS)
    if stipulated:
        flags.append(
            Flag(
                code="STIPULATED_DISMISSAL",
                title="Stipulated dismissal",
                detail=f"Matched “{stipulated.group(0)}”.",
                weight=8,
            )
        )

    business = _search_any(docket.cause + " " + docket.suit_nature + " " + text, BUSINESS_PATTERNS)
    injury = _search_any(text, INJURY_PATTERNS)
    if business and injury:
        flags.append(
            Flag(
                code="CHARACTERIZATION_MISMATCH",
                title="Business dispute with injury-style characterization",
                detail=(
                    f"Docket looks commercial (“{business.group(0)}”) but resolution text "
                    f"uses injury/§104-style language (“{injury.group(0)}”). "
                    "IRC §104(a)(2) excludes damages for personal physical injuries; "
                    "mischaracterization of a business payment as an injury award is a known evasion pattern."
                ),
                weight=25,
            )
        )

    round_amounts = [
        amount
        for amount in amounts
        if amount >= MIN_ROUND_AMOUNT and (amount % 50_000 == 0 or amount % 100_000 == 0)
    ]
    if round_amounts and settlement_indicated:
        pretty = ", ".join(f"${amount:,}" for amount in round_amounts[:4])
        flags.append(
            Flag(
                code="ROUND_DOLLAR_AMOUNT",
                title="Round settlement or judgment amount",
                detail=f"Public text states {pretty}. Round figures are weak alone and stronger with other flags.",
                weight=8,
            )
        )

    surname = shared_surname(docket)
    if surname and settlement_indicated:
        flags.append(
            Flag(
                code="SHARED_SURNAME_PARTIES",
                title="Same surname on both sides",
                detail=(
                    f"Both sides of the caption share the surname “{surname.title()}”. "
                    "Related-party suits can be used to move money under a court stamp. "
                    "This is a name heuristic, not proof of relationship."
                ),
                weight=22,
            )
        )

    structured = _search_any(text, STRUCTURED_PATTERNS)
    if structured:
        flags.append(
            Flag(
                code="STRUCTURED_SETTLEMENT",
                title="Structured settlement / annuity",
                detail=f"Matched “{structured.group(0)}”. Structures are often legitimate; they also spread recognition and can obscure the payor.",
                weight=10,
            )
        )

    assignment = _search_any(text, ASSIGNMENT_PATTERNS)
    if assignment:
        flags.append(
            Flag(
                code="ASSIGNMENT_OF_PROCEEDS",
                title="Assignment of settlement proceeds",
                detail=f"Matched “{assignment.group(0)}”. Assignments can insert a third party into the money trail.",
                weight=12,
            )
        )

    if (
        settlement_indicated
        and days is not None
        and days <= RAPID_DAYS
        and len(docket.document_texts) <= 2
    ):
        flags.append(
            Flag(
                code="MINIMAL_DOCKET_ACTIVITY",
                title="Little public docket activity before resolution",
                detail="Few public filings and a fast termination. May be incomplete RECAP coverage, or a friendly suit.",
                weight=10,
            )
        )

    raw = sum(flag.weight for flag in flags)
    risk_score = min(100, raw)
    if risk_score >= 60:
        band = "HIGH"
    elif risk_score >= 35:
        band = "MEDIUM"
    elif risk_score >= 15:
        band = "LOW"
    else:
        band = "INFO"

    if band in {"HIGH", "MEDIUM"}:
        priority = "REVIEW"
    elif settlement_indicated:
        priority = "BACKGROUND"
    else:
        priority = "IGNORE"

    return ScoredCase(
        watch_name=target.name,
        entity_type=target.entity_type,
        docket=docket,
        flags=flags,
        amounts=amounts,
        settlement_indicated=settlement_indicated,
        risk_score=risk_score,
        risk_band=band,
        review_priority=priority,
    )


def apply_repeat_litigant(results: list[ScoredCase]) -> list[ScoredCase]:
    counts: dict[str, set[str]] = defaultdict(set)
    for item in results:
        if item.docket.docket_id:
            counts[item.watch_name.lower()].add(item.docket.docket_id)

    updated: list[ScoredCase] = []
    for item in results:
        docket_count = len(counts.get(item.watch_name.lower(), set()))
        if docket_count < 2 or not item.settlement_indicated:
            updated.append(item)
            continue
        if any(flag.code == "REPEAT_LITIGANT" for flag in item.flags):
            updated.append(item)
            continue
        extra = Flag(
            code="REPEAT_LITIGANT",
            title="Watch target appears in multiple dockets",
            detail=f"{item.watch_name} matched {docket_count} dockets in this run. Repeat suits can be a pattern or just an active litigant.",
            weight=10,
        )
        flags = [*item.flags, extra]
        score = min(100, sum(flag.weight for flag in flags))
        if score >= 60:
            band = "HIGH"
        elif score >= 35:
            band = "MEDIUM"
        elif score >= 15:
            band = "LOW"
        else:
            band = "INFO"
        priority = "REVIEW" if band in {"HIGH", "MEDIUM"} else item.review_priority
        updated.append(
            ScoredCase(
                watch_name=item.watch_name,
                entity_type=item.entity_type,
                docket=item.docket,
                flags=flags,
                amounts=item.amounts,
                settlement_indicated=item.settlement_indicated,
                risk_score=score,
                risk_band=band,
                review_priority=priority,
            )
        )
    return updated


def lead_narrative(item: ScoredCase) -> str:
    docket = item.docket
    amount_text = (
        ", ".join(f"${amount:,}" for amount in item.amounts[:5]) if item.amounts else "not stated on public docket"
    )
    days = docket.days_open()
    days_text = "unknown" if days is None else f"{days} days"
    flag_lines = "\n".join(
        f"  - {flag.code} ({flag.weight}): {flag.detail}" for flag in item.flags
    ) or "  - none"
    parties = "; ".join(docket.parties) or docket.case_name
    return "\n".join(
        [
            "LEAD SCREENING NARRATIVE — NOT A DETERMINATION OF TAX EVASION",
            "This is a public-record screen for a trained examiner. It is not a finding, not a Form 2797, and not a SAR.",
            "",
            f"Subject (watchlist): {item.watch_name} ({item.entity_type})",
            f"Parties: {parties}",
            f"Case: {docket.case_name}",
            f"Court: {docket.court} ({docket.court_id})",
            f"Docket: {docket.docket_number}",
            f"PACER case id: {docket.pacer_case_id or 'n/a'}",
            f"Filed: {docket.date_filed or 'n/a'}  Terminated: {docket.date_terminated or 'open'}  Days: {days_text}",
            f"Nature / cause: {docket.suit_nature or docket.cause or 'n/a'}",
            f"Amount(s) parsed from public text: {amount_text}",
            f"Risk score: {item.risk_score}  Band: {item.risk_band}  Priority: {item.review_priority}",
            f"Source URL: {docket.url}",
            "",
            "Why this was flagged:",
            flag_lines,
            "",
            "Suggested examiner follow-up if a case is opened:",
            "  1. Compare the complaint’s cause of action with how any settlement is characterized (especially IRC §104(a)(2) physical-injury claims).",
            "  2. Test related-party status of plaintiff, defendant, and any assignee or structured-settlement purchaser.",
            "  3. Match dollars to information returns (1099-MISC/NEC, W-2, or none filed).",
            "  4. If warranted, request the settlement agreement, release, and payment trail.",
            "",
            "Limitation: Public dockets often omit the agreement, the true payor, and tax characterization. Absence of a flag is not clearance.",
        ]
    )
