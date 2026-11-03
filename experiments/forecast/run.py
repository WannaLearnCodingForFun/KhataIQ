"""Forecast monthly net business inflow 1-3 months ahead; compare with simple baselines.

    python experiments/forecast/run.py --businesses 150 --seed 5000

Data: synthetic businesses with 24 months of statements. Each business's monthly net
business inflow comes from the real evidence rules and metrics code run in-process
(khataiq.evidence + khataiq.metrics), not from the generator's own bookkeeping.

Models, all predicting month t+h from data up to month t (h = 1, 2, 3):
  last value       y[t]
  seasonal naive   y[t+h-12] (the same month last year)
  LightGBM         one global model over all businesses: lags 1, 2, 3, 12 (relative to the
                   origin), month of year of the target, horizon, business type.
Rolling origin: for every origin month from 14 to 20 the model is trained only on targets at
or before the origin (from the first month whose 12-month lag exists), then scored on the next
1-3 months. Errors: MAE in paise (integers) and
MAPE in percent. Every origin is an MLflow run (SQLite store).

Decision rule (docs/specs/ml.md): the app shows a forecast only if LightGBM beats seasonal
naive on MAE at every horizon. Beating it on synthetic data is necessary, not sufficient: a
model trained on generated businesses is not shown to officers about real ones.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean

import lightgbm as lgb
import mlflow
import numpy as np

os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")  # offline: no usage pings
os.environ.setdefault("DO_NOT_TRACK", "true")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from khataiq.core.ledger import normalize_narration  # noqa: E402
from khataiq.evidence.duplicate import duplicate_links  # noqa: E402
from khataiq.evidence.loan import loan_links  # noqa: E402
from khataiq.evidence.reversal import reversal_links  # noqa: E402
from khataiq.evidence.self_transfer import self_transfer_links  # noqa: E402
from khataiq.evidence.types import AccountInfo, LedgerTxn  # noqa: E402
from khataiq.metrics.monthly import monthly_metrics  # noqa: E402
from khataiq.pipeline.enrich import channel_of, counterparty_key  # noqa: E402
from synthetic.generator import BUSINESS_TYPES, GenConfig, generate  # noqa: E402

MONTHS = 24
HORIZONS = (1, 2, 3)
FIRST_ORIGIN, LAST_ORIGIN = 14, MONTHS - max(HORIZONS) - 1


def monthly_series(seed: int) -> tuple[str, list[int]]:
    biz = generate(seed, GenConfig(start=date(2024, 11, 1), months=MONTHS))
    txns = []
    for row in sorted(biz.rows.values(), key=lambda r: r.uid):
        norm = normalize_narration(row.narration)
        channel = channel_of(norm)
        txns.append(LedgerTxn(
            id=row.uid, account_id=row.account, upload_id=0, txn_date=row.txn_date,
            amount_paise=row.credit or row.debit,
            direction="credit" if row.credit else "debit", balance_after_paise=0,
            narration_norm=norm, utr=None, counterparty_key=counterparty_key(row.narration,
                                                                             channel),
            fingerprint=str(row.uid), label=row.label))
    accounts = [AccountInfo(i, a.mask, a.upi_id) for i, a in enumerate(biz.accounts)]
    links = (self_transfer_links(txns, accounts) + reversal_links(txns) + duplicate_links(txns)
             + loan_links(txns))
    return biz.business_type, [m.net_business_inflow_paise for m in monthly_metrics(txns, links)]


def features(series: list[int], origin: int, h: int, start_month: int,
             btype: str) -> list[float]:
    target_month = (start_month - 1 + origin + h) % 12 + 1
    return [series[origin], series[origin - 1], series[origin - 2],
            series[origin + h - 12], float(target_month), float(h),
            float(BUSINESS_TYPES.index(btype))]


def mape(actual: list[int], predicted: list[float]) -> float:
    pairs = [(a, p) for a, p in zip(actual, predicted, strict=True) if a != 0]
    return 100 * mean(abs(a - p) / abs(a) for a, p in pairs)


def mae(actual: list[int], predicted: list[float]) -> int:
    return round(mean(abs(a - p) for a, p in zip(actual, predicted, strict=True)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--businesses", type=int, default=150)
    parser.add_argument("--seed", type=int, default=5000)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/results/forecast.md")
    args = parser.parse_args()

    data = [monthly_series(args.seed + i) for i in range(args.businesses)]
    data = [(t, s) for t, s in data if len(s) == MONTHS]
    start_month = 11  # the generated histories start in November
    mlflow.set_tracking_uri(f"sqlite:///{ROOT / 'experiments/forecast/mlflow.db'}")
    mlflow.set_experiment("net-inflow-forecast")

    errors: dict[tuple[str, int], tuple[list[int], list[float]]] = defaultdict(
        lambda: ([], []))
    for origin in range(FIRST_ORIGIN, LAST_ORIGIN + 1):
        x_train, y_train = [], []
        for btype, series in data:
            for o in range(2, origin):
                for h in HORIZONS:
                    # the lag-12 value must exist, and the target must already be observed
                    if o + h - 12 >= 0 and o + h <= origin:
                        x_train.append(features(series, o, h, start_month, btype))
                        y_train.append(series[o + h])
        model = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=15,
                                  min_child_samples=20, verbose=-1, random_state=0)
        model.fit(np.array(x_train), np.array(y_train),
                  categorical_feature=[6] if len(set(t for t, _ in data)) > 1 else "auto")
        with mlflow.start_run(run_name=f"origin-{origin}"):
            mlflow.log_params({"origin": origin, "train_rows": len(y_train),
                               "businesses": len(data)})
            for h in HORIZONS:
                actual = [series[origin + h] for _, series in data]
                feats = np.array([features(s, origin, h, start_month, t) for t, s in data])
                predictions = {
                    "last_value": [float(s[origin]) for _, s in data],
                    "seasonal_naive": [float(s[origin + h - 12]) for _, s in data],
                    "lightgbm": [float(p) for p in model.predict(feats)],
                }
                for name, pred in predictions.items():
                    a, p = errors[(name, h)]
                    a.extend(actual)
                    p.extend(pred)
                    mlflow.log_metric(f"mae_{name}_h{h}", mae(actual, pred))

    rows = {(name, h): (mae(*errors[(name, h)]), mape(*errors[(name, h)]))
            for name in ("last_value", "seasonal_naive", "lightgbm") for h in HORIZONS}
    beats = all(rows[("lightgbm", h)][0] < rows[("seasonal_naive", h)][0] for h in HORIZONS)
    args.out.write_text(render(args, len(data), rows, beats))
    print("LightGBM beats seasonal naive at every horizon:", beats)


def render(args: argparse.Namespace, n: int, rows: dict[tuple[str, int], tuple[int, float]],
           beats: bool) -> str:
    def rupees(paise: int) -> str:
        return f"₹{paise / 100:,.0f}"

    lines = [
        "# Cash-flow forecast experiment",
        "",
        "Generated by `python experiments/forecast/run.py`. Synthetic data only.",
        "",
        f"- {n} synthetic businesses (seeds {args.seed}–{args.seed + n - 1}), 24 months each, "
        "monthly **net business inflow** computed by the real evidence rules and metrics code.",
        f"- Rolling origin: origins at months {FIRST_ORIGIN}–{LAST_ORIGIN}, horizons 1–3; at each "
        "origin LightGBM is retrained on targets already observed. Runs tracked in MLflow "
        "(`experiments/forecast/mlflow.db`).",
        "",
        "| Model | MAE h=1 | MAE h=2 | MAE h=3 | MAPE h=1 | MAPE h=2 | MAPE h=3 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    names = {"last_value": "Last value", "seasonal_naive": "Seasonal naive (same month "
             "last year)", "lightgbm": "LightGBM (lags 1-3, 12; month; type)"}
    for key, label in names.items():
        maes = " | ".join(rupees(rows[(key, h)][0]) for h in HORIZONS)
        mapes = " | ".join(f"{rows[(key, h)][1]:.1f}%" for h in HORIZONS)
        lines.append(f"| {label} | {maes} | {mapes} |")
    margins = ", ".join(
        f"h={h}: {100 * (1 - rows[('lightgbm', h)][0] / rows[('seasonal_naive', h)][0]):.1f}%"
        for h in HORIZONS)
    verdict = (f"LightGBM beats seasonal naive on MAE at every horizon ({margins} lower). "
               "That is necessary but not sufficient: the model was trained and tested on "
               "synthetic businesses, so **the app shows no forecast** until this experiment is "
               "repeated on real statement histories. A margin of a fraction of a percent (if "
               "any horizon shows one) is within noise." if beats else
               f"LightGBM does **not** beat seasonal naive at every horizon ({margins}), so "
               "**the app shows no forecast** (docs/specs/ml.md).")
    lines += [
        "",
        f"**Decision:** {verdict}",
        "",
        "## What this does and doesn't show",
        "",
        "- The generator's seasonality is simple (weekend +20%, October–November +35%) and the "
        "same every year, which favours seasonal naive. Real businesses have trends, shocks "
        "and holidays that move.",
        "- 24 months is the minimum for a 12-month lag; most real borrowers won't have that "
        "much statement history, which limits any forecast in practice.",
        "- MAPE is unstable when a month's net inflow is near zero; MAE (in rupees) is the "
        "primary metric.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
