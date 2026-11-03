"""Seeded generator of small businesses, their bank accounts and statements, with ground truth.

    python -m synthetic.generator --seed 7 --out /tmp/biz7

generate(seed, config) is deterministic: the same seed and config give byte-identical
statements and ground truth. All randomness comes from one random.Random(seed); nothing reads
the clock or iterates over a set.

What a business looks like (docs/specs/synthetic-data.md):
  * 1-3 accounts in the demo_bank CSV format; account 0 is the main current account.
  * Daily UPI sales with weekly seasonality (weekends +20%) and a festival bump (Oct-Nov +35%),
    weekly cash deposits, monthly rent, salaries, an EMI, utilities, bank charges, supplier
    payments, quarterly GST, personal spends and ATM withdrawals.
  * Planted events, all recorded in ground truth: self-transfers between own accounts (most
    with a shared UTR, some without, some posted next day), ambiguous transfers, reversals,
    an overlapping second statement for account 0, near-duplicate rows, a circular flow for
    about one business in three, and a loan disbursal.

References: a row is identified by "a<account>:s<statement>:<line>", the statement line where
it first appears. (The spec's "account:line" isn't enough once account 0 has two overlapping
statements: the same row has a different line in each.)
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from khataiq.pipeline.parsers.demo_csv import render_demo_csv

BUSINESS_TYPES = ("kirana", "pharmacy", "salon", "hardware", "tiffin")
# Typical single sale, in paise, per business type (min, max).
SALE_RANGE = {"kirana": (30_000, 400_000), "pharmacy": (20_000, 300_000),
              "salon": (25_000, 250_000), "hardware": (80_000, 1_500_000),
              "tiffin": (8_000, 120_000)}
FIRST_NAMES = ["RAMESH", "SURESH", "ANITA", "PRIYA", "VIKRAM", "MEENA", "ARJUN", "KAVYA",
               "RAHUL", "SNEHA", "IMRAN", "FATIMA", "JOHN", "DEEPA", "MANOJ", "LATA"]
LAST_NAMES = ["SHARMA", "PATEL", "IYER", "REDDY", "KHAN", "SINGH", "GUPTA", "NAIR", "DAS",
              "JOSHI", "MEHTA", "PILLAI"]
FIRMS = ["TRADERS", "AGENCIES", "DISTRIBUTORS", "ENTERPRISES", "WHOLESALE", "SUPPLY CO"]
BANKS = ["HDFC", "ICIC", "SBIN", "UTIB", "KKBK", "PUNB"]
LENDERS = ["BAJAJ FINANCE", "TATA CAPITAL", "LENDINGKART", "AXIS FINANCE"]
HANDLES = ["okaxis", "okicici", "oksbi", "ybl", "paytm", "ibl"]
MERCHANTS = ["ZOMATO", "SWIGGY", "AMAZON", "FLIPKART", "BIGBASKET", "UBER", "IRCTC"]
REVERSAL_WORDS = ["REFUND", "REV", "REVERSAL", "FAILED"]


@dataclass(frozen=True)
class GenConfig:
    start: date = date(2026, 5, 1)
    months: int = 6
    min_accounts: int = 1
    max_accounts: int = 3
    self_transfers_per_month: int = 4
    utr_share_pct: int = 70
    next_day_pct: int = 10
    ambiguous_every_months: int = 2
    reversals_per_month: int = 2
    near_duplicates_every_months: int = 3
    cycle_one_in: int = 3
    overlap_days: tuple[int, int] = (10, 20)


@dataclass
class Row:
    uid: int
    account: int
    txn_date: date
    narration: str
    debit: int
    credit: int
    label: str


@dataclass
class Statement:
    account_index: int
    statement_index: int
    opening_paise: int
    uids: list[int]
    csv: bytes
    lines: dict[int, int]  # uid -> line number in this statement


@dataclass
class AccountSpec:
    mask: str
    upi_id: str | None


@dataclass
class GeneratedBusiness:
    seed: int
    name: str
    business_type: str
    accounts: list[AccountSpec]
    statements: list[Statement]
    ground_truth: dict[str, Any]
    rows: dict[int, Row] = field(repr=False, default_factory=dict)


class _Builder:
    def __init__(self, seed: int, config: GenConfig) -> None:
        self.rng = random.Random(seed)
        self.config = config
        self.rows: list[Row] = []
        self.utr_counter = self.rng.randrange(10**11, 9 * 10**11)
        self.truth: dict[str, list[Any]] = {"self_transfers": [], "reversals": [],
                                            "duplicates": [], "cycles": [], "loans": []}
        self.end = self._add_months(config.start, config.months) - timedelta(days=1)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _add_months(day: date, months: int) -> date:
        month = day.month - 1 + months
        return date(day.year + month // 12, month % 12 + 1, 1)

    def utr(self) -> str:
        self.utr_counter += self.rng.randrange(1, 9_999)
        return f"{self.utr_counter:012d}"

    def person(self) -> str:
        return f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}"

    def firm(self) -> str:
        return f"{self.rng.choice(LAST_NAMES)} {self.rng.choice(FIRMS)}"

    def ifsc(self) -> str:
        return f"{self.rng.choice(BANKS)}0{self.rng.randrange(100_000, 999_999)}"

    def vpa(self, name: str) -> str:
        handle = name.split()[0].lower() + str(self.rng.randrange(10, 99))
        return f"{handle}@{self.rng.choice(HANDLES)}"

    def add(self, account: int, day: date, narration: str, debit: int, credit: int,
            label: str) -> Row:
        row = Row(len(self.rows) + 1, account, day, narration, debit, credit, label)
        self.rows.append(row)
        return row

    def days(self) -> list[date]:
        return [self.config.start + timedelta(days=i)
                for i in range((self.end - self.config.start).days + 1)]

    def month_starts(self) -> list[date]:
        return [self._add_months(self.config.start, m) for m in range(self.config.months)]

    def amount(self, low: int, high: int) -> int:
        """An amount in paise with non-round paise, like a real card or UPI payment."""
        return self.rng.randrange(low, high)

    def round_amount(self, low_rupees: int, high_rupees: int, step: int = 500) -> int:
        return self.rng.randrange(low_rupees // step, high_rupees // step + 1) * step * 100


def generate(seed: int, config: GenConfig | None = None) -> GeneratedBusiness:
    config = config or GenConfig()
    b = _Builder(seed, config)
    rng = b.rng
    business_type = rng.choice(BUSINESS_TYPES)
    owner = b.person()
    name = f"{owner.split()[1].title()} {business_type.title()}"
    n_accounts = rng.randint(config.min_accounts, config.max_accounts)
    masks = rng.sample(range(1000, 9999), n_accounts)
    owner_vpa = b.vpa(owner)
    accounts = [AccountSpec(f"{m:04d}", owner_vpa if i == 0 else None)
                for i, m in enumerate(masks)]
    others = list(range(1, n_accounts))

    customers = [(c, b.vpa(c)) for c in (b.person() for _ in range(30))]
    suppliers = [(s, b.ifsc()) for s in (b.firm() for _ in range(6))]
    staff = [(p, b.ifsc()) for p in (b.person() for _ in range(rng.randint(2, 4)))]
    landlord, landlord_ifsc = b.person(), b.ifsc()
    lender = rng.choice(LENDERS)
    low, high = SALE_RANGE[business_type]

    # ------------------------------------------------------------------ everyday flows
    for day in b.days():
        multiplier = 100
        if day.weekday() >= 5:
            multiplier += 20
        if day.month in (10, 11):
            multiplier += 35
        for _ in range(rng.randint(1, 3)):
            cust, vpa = rng.choice(customers)
            amount = b.amount(low, high) * multiplier // 100
            account = 0 if not others or rng.random() < 0.75 else rng.choice(others)
            b.add(account, day, f"UPI/{cust}/{vpa}/{b.utr()}", 0, amount, "sales")
        if day.weekday() == 5:
            b.add(0, day, f"CASH DEP {rng.choice(['MG ROAD', 'MAIN BAZAAR', 'STATION RD'])}",
                  0, b.round_amount(2_000, 20_000, 100), "cash_deposit")
    for month in b.month_starts():
        def on(day: int, m: date = month) -> date:
            return m + timedelta(days=day - 1)

        b.add(0, on(5), f"NEFT/{landlord_ifsc}/{landlord}", b.round_amount(12_000, 40_000),
              0, "rent")
        for person, ifsc in staff:
            b.add(0, on(1), f"NEFT/{ifsc}/{person}", b.round_amount(9_000, 22_000), 0,
                  "salary_paid")
        b.add(0, on(rng.randint(8, 12)), f"UPI/BESCOM/bescom@ybl/{b.utr()}",
              b.amount(80_000, 600_000), 0, "utilities")
        b.add(0, on(28), "SMS ALERT CHARGES", 1_770, 0, "bank_charges")
        for _ in range(rng.randint(4, 8)):
            supplier, ifsc = rng.choice(suppliers)
            account = rng.choice([0, *others])
            b.add(account, on(rng.randint(2, 27)), f"NEFT/{ifsc}/{supplier}",
                  b.amount(500_000, 4_000_000), 0, "supplier_payment")
        for _ in range(4):
            merchant = rng.choice(MERCHANTS)
            b.add(rng.choice([0, *others]), on(rng.randint(1, 28)),
                  f"UPI/{merchant}/{merchant.lower()}@{rng.choice(HANDLES)}/{b.utr()}",
                  b.amount(5_000, 300_000), 0, "personal")
        for _ in range(2):
            b.add(0, on(rng.randint(1, 28)), f"ATM WDL {rng.choice(['MG ROAD', 'KORAMANGALA'])}",
                  b.round_amount(1_000, 10_000, 500), 0, "cash_withdrawal")
        if month.month in (1, 4, 7, 10):
            b.add(0, on(20), "GST PMT CBIC CHALLAN", b.amount(500_000, 3_000_000), 0, "tax")

    # ------------------------------------------------------------------ loan + EMIs
    loan_day = config.start + timedelta(days=rng.randint(20, 45))
    loan = b.add(0, loan_day, f"NEFT/{b.ifsc()}/{lender} LOAN DISB",
                 0, b.round_amount(100_000, 1_000_000, 10_000), "loan_in")
    b.truth["loans"].append(loan.uid)
    emi = loan.credit // 24
    for month in b.month_starts():
        emi_day = month + timedelta(days=6)
        if emi_day > loan_day:
            b.add(0, emi_day, f"ACH D- {lender} EMI", emi, 0, "emi")

    # ------------------------------------------------------------------ self-transfers
    if others:
        for month in b.month_starts():
            for _ in range(config.self_transfers_per_month):
                src, dst = rng.sample(range(n_accounts), 2)
                day = month + timedelta(days=rng.randint(0, 26))
                amount = b.round_amount(10_000, 200_000, 1_000)
                later = day + timedelta(days=1 if rng.randrange(100) < config.next_day_pct
                                        else 0)
                if rng.randrange(100) < config.utr_share_pct:
                    utr = b.utr()
                    out = b.add(src, day, f"UPI/{owner}/{owner_vpa}/{utr}", amount, 0, "transfer")
                    into = b.add(dst, later, f"UPI/{owner}/{owner_vpa}/{utr}", 0, amount,
                                 "transfer")
                else:
                    out = b.add(src, day, f"NEFT/{b.ifsc()}/{owner}", amount, 0, "transfer")
                    into = b.add(dst, later, f"NEFT/{b.ifsc()}/{owner}", 0, amount, "transfer")
                b.truth["self_transfers"].append([out.uid, into.uid, "verified"])
        for i, month in enumerate(b.month_starts()):
            if i % config.ambiguous_every_months:
                continue
            dst = rng.choice(others)
            day = month + timedelta(days=rng.randint(3, 20))
            amount = b.round_amount(20_000, 90_000, 5_000)
            out = b.add(0, day, f"NEFT/{b.ifsc()}/{owner}", amount, 0, "transfer")
            into = b.add(dst, day, f"NEFT/{b.ifsc()}/{owner}", 0, amount, "transfer")
            cust, vpa = rng.choice(customers)
            b.add(dst, day + timedelta(days=1), f"UPI/{cust}/{vpa}/{b.utr()}", 0, amount, "sales")
            b.truth["self_transfers"].append([out.uid, into.uid, "unresolved"])

    # ------------------------------------------------------------------ reversals
    for month in b.month_starts():
        for _ in range(config.reversals_per_month):
            merchant = rng.choice(MERCHANTS)
            vpa = f"{merchant.lower()}@{rng.choice(HANDLES)}"
            account = rng.choice([0, *others])
            day = month + timedelta(days=rng.randint(0, 20))
            amount = b.amount(10_000, 3_000_000)
            paid = b.add(account, day, f"UPI/{merchant}/{vpa}/{b.utr()}", amount, 0, "personal")
            back = b.add(account, day + timedelta(days=rng.randint(0, 7)),
                         f"UPI/{rng.choice(REVERSAL_WORDS)}/{merchant}/{vpa}/{b.utr()}",
                         0, amount, "refund")
            b.truth["reversals"].append([back.uid, paid.uid])

    # ------------------------------------------------------------------ circular flow
    if rng.randrange(config.cycle_one_in) == 0:
        day = config.start + timedelta(days=rng.randint(30, 120))
        amount = b.round_amount(50_000, 200_000, 1_000)

        def near(x: int) -> int:
            return x * rng.randint(95, 105) // 100

        alpha, alpha_ifsc = b.firm() + " IMPEX", b.ifsc()
        legs = [b.add(0, day, f"NEFT/{alpha_ifsc}/{alpha}", amount, 0, "other")]
        if not others:
            legs.append(b.add(0, day + timedelta(days=rng.randint(5, 20)),
                              f"NEFT/{alpha_ifsc}/{alpha}", 0, near(amount), "other"))
        else:
            via = others[0]
            back_in = near(amount)
            legs.append(b.add(via, day + timedelta(days=4), f"NEFT/{alpha_ifsc}/{alpha}", 0,
                              back_in, "other"))
            if rng.random() < 0.5:  # 3 hops: back to account 0 as a self-transfer
                utr = b.utr()
                legs.append(b.add(via, day + timedelta(days=8),
                                  f"UPI/{owner}/{owner_vpa}/{utr}", back_in, 0, "transfer"))
                legs.append(b.add(0, day + timedelta(days=8),
                                  f"UPI/{owner}/{owner_vpa}/{utr}", 0, back_in, "transfer"))
                b.truth["self_transfers"].append([legs[-2].uid, legs[-1].uid, "verified"])
            else:  # 4 hops: through a second counterparty
                beta, beta_ifsc = b.firm() + " EXPORTS", b.ifsc()
                legs.append(b.add(via, day + timedelta(days=8), f"NEFT/{beta_ifsc}/{beta}",
                                  near(back_in), 0, "other"))
                legs.append(b.add(0, day + timedelta(days=14), f"NEFT/{beta_ifsc}/{beta}", 0,
                                  near(legs[-1].debit), "other"))
        b.truth["cycles"].append([leg.uid for leg in legs])

    return _render(seed, name, business_type, accounts, b)


def _render(seed: int, name: str, business_type: str, accounts: list[AccountSpec],
            b: _Builder) -> GeneratedBusiness:
    rng, config = b.rng, b.config
    by_account: dict[int, list[Row]] = {i: [] for i in range(len(accounts))}
    for row in b.rows:
        by_account[row.account].append(row)
    statements: list[Statement] = []
    first_seen: dict[int, tuple[int, int, int]] = {}

    for index in range(len(accounts)):
        rows = sorted(by_account[index], key=lambda r: (r.txn_date, r.uid))
        running, lowest = 0, 0
        for row in rows:
            running += row.credit - row.debit
            lowest = min(lowest, running)
        opening = -lowest + b.round_amount(50_000, 300_000, 1_000)
        if index != 0:
            statements.append(_statement(index, 0, opening, rows, first_seen))
            continue

        # Account 0 comes as two statements that overlap by 10-20 days, plus near-duplicate
        # rows: copies of the first statement's last-day rows that appear again in the second
        # statement with a different running balance.
        split = config.start + (b.end - config.start) // 2
        overlap = rng.randint(*config.overlap_days)
        first_part = [r for r in rows if r.txn_date <= split]
        last_day_rows = [r for r in first_part if r.txn_date == split]
        wanted = max(1, config.months // config.near_duplicates_every_months)
        n_dups = min(len(last_day_rows), wanted)
        copies: list[Row] = []
        for original in last_day_rows[:n_dups]:
            copy = Row(len(b.rows) + len(copies) + 1, 0, original.txn_date, original.narration,
                       original.debit, original.credit, original.label)
            copies.append(copy)
            b.truth["duplicates"].append([original.uid, copy.uid])
        b.rows.extend(copies)
        start_second = split - timedelta(days=overlap - 1)
        second_part = [r for r in rows if r.txn_date >= start_second]
        cut = max(i for i, r in enumerate(second_part) if r.txn_date <= split) + 1
        second_part = second_part[:cut] + copies + second_part[cut:]
        before_second = sum(r.credit - r.debit for r in rows if r.txn_date < start_second)
        statements.append(_statement(0, 0, opening, first_part, first_seen))
        statements.append(_statement(0, 1, opening + before_second, second_part, first_seen))

    def ref(uid: int) -> str:
        account, statement, line = first_seen[uid]
        return f"a{account}:s{statement}:{line}"

    truth = b.truth
    ground_truth = {
        "self_transfers": [[ref(d), ref(c), level] for d, c, level in truth["self_transfers"]],
        "reversals": [[ref(c), ref(d)] for c, d in truth["reversals"]],
        "duplicates": [[ref(a), ref(c)] for a, c in truth["duplicates"]],
        "cycles": [[ref(u) for u in cycle] for cycle in truth["cycles"]],
        "loans": [ref(u) for u in truth["loans"]],
        "labels": {ref(r.uid): r.label for r in sorted(b.rows, key=lambda r: r.uid)},
    }
    return GeneratedBusiness(seed, name, business_type, accounts, statements, ground_truth,
                             {r.uid: r for r in b.rows})


def _statement(account: int, index: int, opening: int, rows: list[Row],
               first_seen: dict[int, tuple[int, int, int]]) -> Statement:
    csv_bytes = render_demo_csv(opening, [(r.txn_date, r.narration, r.debit, r.credit)
                                          for r in rows])
    lines = {r.uid: 3 + i for i, r in enumerate(rows)}  # line 1 opening, line 2 header
    for uid, line in lines.items():
        first_seen.setdefault(uid, (account, index, line))
    return Statement(account, index, opening, [r.uid for r in rows], csv_bytes, lines)


def write(business: GeneratedBusiness, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for st in business.statements:
        (out / f"account{st.account_index}_statement{st.statement_index}.csv").write_bytes(st.csv)
    meta = {"seed": business.seed, "name": business.name, "type": business.business_type,
            "accounts": [{"mask": a.mask, "upi_id": a.upi_id} for a in business.accounts]}
    (out / "business.json").write_text(json.dumps(meta, indent=1) + "\n")
    (out / "ground_truth.json").write_text(json.dumps(business.ground_truth, indent=1) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    business = generate(args.seed)
    write(business, args.out)
    print(f"{business.name}: {len(business.accounts)} accounts, "
          f"{len(business.statements)} statements -> {args.out}")


if __name__ == "__main__":
    main()
