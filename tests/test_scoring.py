from __future__ import annotations

import unittest
from datetime import date
from typing import Any

from settlement_watch.models import DocketRecord, WatchTarget
from settlement_watch.scoring import apply_repeat_litigant, extract_amounts, score_docket


def docket(**overrides: Any) -> DocketRecord:
    base: dict[str, Any] = dict(
        docket_id="1",
        case_name="Acme LLC v. Beta LLC",
        court="District Court, S.D. New York",
        court_id="nysd",
        docket_number="1:24-cv-1",
        date_filed=date(2024, 1, 2),
        date_terminated=date(2024, 1, 18),
        cause="28:1332 Diversity-Contract",
        suit_nature="Contract - Other",
        jurisdiction="Diversity",
        assigned_to="Judge",
        pacer_case_id="1",
        url="https://www.courtlistener.com/docket/1/",
        parties=["Acme LLC", "Beta LLC"],
        attorneys=["A"],
        document_texts=["STIPULATION of Dismissal. Settlement of contract claims."],
    )
    base.update(overrides)
    return DocketRecord(**base)


class ScoringTests(unittest.TestCase):
    def test_extracts_round_and_odd_amounts(self):
        self.assertEqual(extract_amounts("paid $500,000 and $87,412.18"), [500000, 87412])

    def test_fast_related_injury_characterization_is_high(self):
        target = WatchTarget("Harbor Creek Holdings LLC", "company")
        record = docket(
            case_name="Harbor Creek Holdings LLC v. Harbor Creek Partners LLC",
            parties=["Harbor Creek Holdings LLC", "Harbor Creek Partners LLC"],
            document_texts=[
                "Consent judgment in the amount of $500,000 characterized as damages "
                "for personal physical injury. Settlement confidential and sealed."
            ],
        )
        scored = score_docket(target, record)
        codes = {flag.code for flag in scored.flags}
        self.assertIn("RAPID_RESOLUTION", codes)
        self.assertIn("CHARACTERIZATION_MISMATCH", codes)
        self.assertIn("SHARED_SURNAME_PARTIES", codes)
        self.assertIn("CONSENT_JUDGMENT", codes)
        self.assertGreaterEqual(scored.risk_score, 60)
        self.assertEqual(scored.risk_band, "HIGH")
        self.assertEqual(scored.review_priority, "REVIEW")

    def test_long_employment_settlement_is_not_high(self):
        target = WatchTarget("Maria Alvarez", "person")
        record = docket(
            case_name="Alvarez v. National Parcel Service Inc",
            parties=["Maria Alvarez", "National Parcel Service Inc"],
            date_filed=date(2022, 3, 1),
            date_terminated=date(2024, 6, 15),
            cause="28:1331 Fed. Question - Employment",
            suit_nature="Employment",
            document_texts=["Joint stipulation of settlement and dismissal with prejudice."],
        )
        scored = score_docket(target, record)
        self.assertLess(scored.risk_score, 35)
        self.assertNotEqual(scored.risk_band, "HIGH")
        self.assertNotIn(
            "CHARACTERIZATION_MISMATCH", {flag.code for flag in scored.flags}
        )

    def test_open_complaint_is_not_a_review_lead(self):
        target = WatchTarget("Pacific Rim Textiles Inc", "company")
        record = docket(
            case_name="Pacific Rim Textiles Inc v. Ocean Freight LLC",
            parties=["Pacific Rim Textiles Inc", "Ocean Freight LLC"],
            date_terminated=None,
            document_texts=["COMPLAINT for goods sold and delivered. Seeks $87,412.18."],
        )
        scored = score_docket(target, record)
        self.assertFalse(scored.settlement_indicated)
        self.assertEqual(scored.review_priority, "IGNORE")

    def test_repeat_litigant_flag_added_across_dockets(self):
        target = WatchTarget("Acme LLC", "company")
        a = score_docket(target, docket(docket_id="10"))
        b = score_docket(
            target,
            docket(
                docket_id="11",
                docket_number="1:24-cv-2",
                case_name="Acme LLC v. Other LLC",
                parties=["Acme LLC", "Other LLC"],
            ),
        )
        updated = apply_repeat_litigant([a, b])
        self.assertTrue(all(
            any(flag.code == "REPEAT_LITIGANT" for flag in item.flags)
            for item in updated
        ))


if __name__ == "__main__":
    unittest.main()
