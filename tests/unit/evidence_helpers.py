from datetime import date, timedelta
from itertools import count

from khataiq.evidence.types import LedgerTxn

D0 = date(2026, 10, 1)
_ids = count(1)


def lt(account=1, day=0, amount=100_000, direction="credit", narration="UPI/X", cp=None,
       utr=None, upload=1, fp=None, label=None, id=None) -> LedgerTxn:
    i = id or next(_ids)
    return LedgerTxn(id=i, account_id=account, upload_id=upload,
                     txn_date=D0 + timedelta(days=day), amount_paise=amount,
                     direction=direction, balance_after_paise=0, narration_norm=narration,
                     utr=utr, counterparty_key=cp, fingerprint=fp or f"fp{i}", label=label)
