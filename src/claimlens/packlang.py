"""Claim Pack translations: labels plus pack sentences, one call per language.

Amounts, codes, and dates are never translated — they are copied by code.
English packs keep the original wording with no extra call.
"""

from typing import Any

from pydantic import BaseModel, Field

from claimlens.schema import strict_schema_of

LANG_NAMES = {"en": "English", "vi": "Vietnamese"}


def source_sentences() -> dict[str, str]:
    from claimlens.claimpack import (
        CHECKLIST,
        GENERIC_DEADLINE,
        PII_CHECK_MARK,
        POLICY_LINE,
        TRANSLATION_NOTE,
    )
    from claimlens.codes import DISCLAIMER as CODE_DISCLAIMER

    return {
        "policy_line": POLICY_LINE,
        "translation_note": TRANSLATION_NOTE,
        "pii_mark": PII_CHECK_MARK,
        "check_0": CHECKLIST[0],
        "check_1": CHECKLIST[1],
        "check_2": CHECKLIST[2],
        "deadline": GENERIC_DEADLINE,
        "t_pack_title": "Claim Pack",
        "h_patient": "Patient and visit",
        "h_codes": "Diagnosis codes",
        "h_bill": "Itemized bill (KRW)",
        "h_checklist": "Checklist before leaving",
        "h_deadlines": "Filing deadlines",
        "f_name": "Name",
        "f_dob": "Date of birth",
        "f_passport": "Passport",
        "f_pid": "Patient ID",
        "f_hospital": "Hospital",
        "f_stay": "Stay",
        "stay_in": "inpatient",
        "stay_out": "outpatient",
        "f_certificate": "Certificate",
        "f_kcd": "KCD",
        "f_who": "WHO ICD-10",
        "f_cm": "ICD-10-CM candidate",
        "t_needed": "Needed to narrow",
        "t_warning": "Warning",
        "t_note_estimate": (
            "Note: the certificate marks a clinical estimate; "
            "a final diagnosis may be requested."
        ),
        "f_total": "Total",
        "f_verified": "Receipt arithmetic verified",
        "differs": "differs between documents",
        "d_disclaimer": CODE_DISCLAIMER,
    }


class PackLabel(BaseModel):
    ko: str = Field(description="Korean label, copied exactly.")
    text: str = Field(description="Short translation of the label.")


class PackSentence(BaseModel):
    key: str = Field(description="Sentence key, copied exactly.")
    text: str = Field(description="Translation of the sentence.")


class PackTranslation(BaseModel):
    labels: list[PackLabel] = Field(description="One pair per input label.")
    sentences: list[PackSentence] = Field(description="One pair per sentence key.")


def pack_schema() -> dict[str, Any]:
    return strict_schema_of(PackTranslation)


PREAMBLE = """Translate a hospital claim pack from English and Korean into {language}.
The Labels are Korean charge names: copy each into ko exactly and give a
short {language} equivalent in text. The Sentences are English pack wording:
copy each key exactly and translate its text. Keep codes (KCD, WHO ICD-10,
ICD-10-CM), amounts, and dates exactly as they appear; translate only the
wording. Never add explanations."""


def translate_pack(lang: str, labels: list[str], provider: Any) -> dict[str, Any]:
    """One strict-schema call; every label and sentence key must come back."""
    if lang not in LANG_NAMES or lang == "en":
        raise ValueError(f"Translation is only needed past English, not {lang!r}.")
    sentences = source_sentences()
    listed = "\n".join(f"- {label}" for label in labels)
    keyed = "\n".join(f"- {key}: {text}" for key, text in sentences.items())
    draft = provider.write(
        f"{PREAMBLE.format(language=LANG_NAMES[lang])}\nLabels:\n{listed}\nSentences:\n{keyed}",
        pack_schema(),
        PackTranslation,
    )
    table = {pair["ko"]: pair["text"] for pair in draft.get("labels", [])}
    missing = [label for label in labels if label not in table]
    if missing:
        raise ValueError(f"Untranslated labels: {missing}.")
    rendered = {pair["key"]: pair["text"] for pair in draft.get("sentences", [])}
    missing_keys = [key for key in sentences if key not in rendered]
    if missing_keys:
        raise ValueError(f"Untranslated sentences: {missing_keys}.")
    return {"labels": table, "sentences": rendered}
