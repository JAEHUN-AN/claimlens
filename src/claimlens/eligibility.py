"""Health-insurance eligibility mini-rule (SPEC 3.5). Deterministic, no model."""

import calendar
from datetime import date
from typing import Any

SPECIAL_VISAS = {"F-5", "E-9", "F-6", "D-2", "D-4-3"}


def _parse(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        year, month, day = (int(part) for part in value.strip().split("-"))
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def _add_months(day: date, months: int) -> date:
    total = day.year * 12 + (day.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def _visa_code(visa: Any) -> str:
    if not isinstance(visa, str):
        return ""
    code = visa.strip().upper().split()[0].split("/")[0].strip()
    return code


def check_eligibility(person: dict[str, Any], service_date: str) -> dict[str, str]:
    """Return one of nhi_member, not_member_or_unknown, work_injury with basis."""
    service = _parse(service_date)
    entry = _parse(person.get("entry_date"))
    registration = _parse(person.get("alien_registration_date"))
    employer = bool(person.get("korean_employer", False))
    arrears = bool(person.get("premium_arrears", False))
    work_related = bool(person.get("work_related", False))
    illegal = bool(person.get("illegal_stay", False))
    excluded = bool(person.get("foreign_insurance_exclusion", False))
    overseas = person.get("overseas_days_in_6months", person.get("overseas_days", 0))
    try:
        overseas_days = int(overseas or 0)
    except (ValueError, TypeError):
        overseas_days = 0

    if work_related:
        return {
            "outcome": "work_injury",
            "rule": "row7_work_injury",
            "basis": "Work-related injury goes to industrial-accident insurance first, "
            "regardless of nationality or visa. Legal basis: Industrial Accident "
            "Compensation Insurance Act priority for work injuries.",
        }
    if illegal or excluded:
        return {
            "outcome": "not_member_or_unknown",
            "rule": "row5_ineligible",
            "basis": "Cannot enroll with unlawful stay or exclusion via foreign insurance. "
            "Legal basis: National Health Insurance Act Article 109(5).",
        }
    if arrears:
        return {
            "outcome": "not_member_or_unknown",
            "rule": "row6_arrears",
            "basis": "No benefits until premium arrears are paid in full. Human review; "
            "no amount calculated. Legal basis: National Health Insurance Act "
            "Article 109(10).",
        }
    if employer and registration is not None and service is not None and service >= registration:
        return {
            "outcome": "nhi_member",
            "rule": "row1_workplace",
            "basis": "Workplace subscriber from the first working day. Legal basis: "
            "National Health Insurance Act Article 109(2).",
        }
    if _visa_code(person.get("visa")) in SPECIAL_VISAS:
        anchors = [d for d in (entry, registration) if d is not None]
        eligible = max(anchors) if anchors else None
        if eligible is not None and service is not None and service >= eligible:
            return {
                "outcome": "nhi_member",
                "rule": "row2_special_visa",
                "basis": "Eligible visa holder covered from entry (or registration when "
                "later). Legal basis: Enforcement Rules Article 61-2(1) items 1-4.",
            }
        return {
            "outcome": "not_member_or_unknown",
            "rule": "row2_special_visa",
            "basis": "Eligible visa but service date is before coverage starts. Human "
            "review; no amount calculated. Legal basis: Enforcement Rules "
            "Article 61-2(1) items 1-4.",
        }
    if bool(person.get("is_dependent", False)):
        relation = str(person.get("relation", person.get("dependent_relation", ""))).lower()
        age = person.get("age")
        try:
            age_int = int(age) if age is not None else None
        except (ValueError, TypeError):
            age_int = None
        exempt = relation == "spouse" or (relation == "child" and age_int is not None and age_int < 19)
        if exempt and registration is not None:
            return {
                "outcome": "nhi_member",
                "rule": "row4_dependent",
                "basis": "Dependent spouse or under-19 child is exempt from the 6-month "
                "wait. Legal basis: National Health Insurance Act Article 109(4)3.",
            }
        if registration is not None and service is not None and overseas_days <= 30:
            eligible = _add_months(registration, 6)
            from datetime import timedelta

            eligible += timedelta(days=1)
            if service >= eligible:
                return {
                    "outcome": "nhi_member",
                    "rule": "row4_dependent",
                    "basis": "Dependent covered after 6 months residence. Legal basis: "
                    "National Health Insurance Act Article 109(4)3.",
                }
        return {
            "outcome": "not_member_or_unknown",
            "rule": "row4_dependent",
            "basis": "Dependent needs 6 months residence (spouse and under-19 children "
            "exempt). Human review; no amount calculated. Legal basis: National "
            "Health Insurance Act Article 109(4)3.",
        }
    if registration is not None and service is not None and overseas_days <= 30:
        from datetime import timedelta

        eligible = _add_months(registration, 6) + timedelta(days=1)
        if service >= eligible:
            return {
                "outcome": "nhi_member",
                "rule": "row3_six_month",
                "basis": "Other registered foreigner covered the day after 6 months "
                "residence (up to 30 days abroad counts as residence). Legal basis: "
                "Act Article 109(3), Enforcement Rules Article 61-2, Notice Article 4.",
            }
    return {
        "outcome": "not_member_or_unknown",
        "rule": "row3_six_month",
        "basis": "Short visit or insufficient residence; no 40 percent amount is "
        "calculated because Act Articles 5, 53 and 54 may not cover Article 109 "
        "non-members. Human review. Legal basis: Act Article 109(3).",
    }
