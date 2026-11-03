"""Rule labeller: an ordered, versioned table of narration patterns. First match wins.

A rule's id and version are stored on the label it produces, so every rule label can be
explained ("RENT_KEYWORD v1 matched 'RENT'"). Changing a pattern means bumping its version.
Patterns run on the normalized narration (uppercase, single spaces, no spaces around '/').
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from khataiq.models.enums import TxnLabel


@dataclass(frozen=True)
class LabelRule:
    rule_id: str
    version: int
    pattern: re.Pattern[str]
    direction: str | None  # "debit", "credit" or None for either
    label: TxnLabel


def _rule(rule_id: str, pattern: str, direction: str | None, label: TxnLabel,
          version: int = 1) -> LabelRule:
    return LabelRule(rule_id, version, re.compile(pattern), direction, label)


# Order matters: specific before general (a "LOAN EMI" debit is an EMI, not a loan credit).
RULES: tuple[LabelRule, ...] = (
    _rule("REVERSAL_KEYWORD", r"\b(REFUND|REV|REVERSAL|FAILED|RTN|RETURN)\b", "credit",
          TxnLabel.REFUND),
    _rule("EMI_KEYWORD", r"\b(EMI|NACH|ECS)\b|\bACH D\b", "debit", TxnLabel.EMI),
    _rule("LOAN_DISBURSAL", r"LOAN DISB|\bDISB(URSAL|URSEMENT)?\b|\bNBFC\b", "credit",
          TxnLabel.LOAN_IN),
    _rule("SALARY_KEYWORD", r"\bSAL(ARY)?\b|\bPAYROLL\b|\bWAGES\b", "debit",
          TxnLabel.SALARY_PAID),
    _rule("RENT_KEYWORD", r"\bRENT\b", "debit", TxnLabel.RENT),
    _rule("CASH_DEPOSIT", r"\bCASH DEP(OSIT)?\b|\bBY CASH\b|\bCDM\b", "credit",
          TxnLabel.CASH_DEPOSIT),
    _rule("ATM_WITHDRAWAL", r"\bATM\b.*\bWDL\b|\bATW\b|\bCASH WDL\b|\bNFS\b", "debit",
          TxnLabel.CASH_WITHDRAWAL),
    _rule("TAX_PAYMENT", r"\bGST\b|\bTDS\b|\bCBIC\b|\bINCOME TAX\b|\bOLTAS\b", "debit",
          TxnLabel.TAX),
    _rule("BANK_CHARGES", r"\bCHARGES?\b|\bCHRGS?\b|\bAMC\b|\bSMS ALERT\b|\bMIN BAL\b",
          "debit", TxnLabel.BANK_CHARGES),
    _rule("UTILITY_BILLER", r"\b(BESCOM|MSEDCL|TNEB|ELECTRICITY|BSNL|AIRTEL|JIO|"
          r"WATER BOARD|MAHANAGAR GAS|INDANE)\b", "debit", TxnLabel.UTILITIES),
)

RULES_VERSION = "rules-v1"


def rule_label(narration_norm: str, direction: str) -> LabelRule | None:
    for rule in RULES:
        if rule.direction not in (None, direction):
            continue
        if rule.pattern.search(narration_norm):
            return rule
    return None
