"""Credit-risk benchmark on Home Credit's application_train.csv.

    python experiments/risk_benchmark/run.py          # needs the data, see README.md
    python experiments/risk_benchmark/run.py --smoke  # random rows; checks the code path only

Models: logistic regression (median imputation, scaling, one-hot) as the baseline; LightGBM.
Split: stratified 80/20 by applicant, fixed seed. Metrics on the held-out 20%: ROC-AUC, PR-AUC
(average precision), Brier score; a calibration curve for both models and a SHAP summary for
LightGBM.

Leakage check (also written to the results page): only application-time columns from
application_train.csv are used; SK_ID_CURR (an id) and TARGET are dropped from the features;
the script asserts no feature is perfectly correlated with the target and that no applicant
appears in both splits.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import lightgbm as lgb  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import shap  # noqa: E402
from sklearn.calibration import calibration_curve  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "experiments/risk_benchmark/data/application_train.csv"
RESULTS = ROOT / "docs/results"
SEED = 7


def load(smoke: bool) -> pd.DataFrame:
    if smoke:
        rng = np.random.default_rng(SEED)
        n = 600
        frame = pd.DataFrame({
            "SK_ID_CURR": np.arange(n), "AMT_INCOME_TOTAL": rng.lognormal(12, 0.5, n),
            "AMT_CREDIT": rng.lognormal(13, 0.6, n), "DAYS_BIRTH": -rng.integers(7000, 25000, n),
            "EXT_SOURCE_2": rng.random(n), "NAME_CONTRACT_TYPE": rng.choice(["Cash", "Rev"], n),
        })
        risk = 1 / (1 + np.exp(4 * frame["EXT_SOURCE_2"] - 1.5))
        frame["TARGET"] = (rng.random(n) < risk).astype(int)
        return frame
    if not DATA.is_file():
        sys.exit(f"{DATA} not found: see experiments/risk_benchmark/README.md")
    return pd.read_csv(DATA)


def leakage_checks(frame: pd.DataFrame, features: list[str]) -> list[str]:
    notes = ["`SK_ID_CURR` and `TARGET` are excluded from the features."]
    numeric = frame[features].select_dtypes("number")
    correlations = numeric.corrwith(frame["TARGET"]).abs().dropna()
    worst = correlations.sort_values(ascending=False).head(1)
    assert (correlations < 0.99).all(), f"suspiciously predictive feature: {worst.to_dict()}"
    if not worst.empty:
        notes.append(f"Strongest single numeric correlation with the target: "
                     f"`{worst.index[0]}` at {worst.iloc[0]:.3f} (no feature is a proxy for it).")
    notes.append("Only `application_train.csv` (information known at application time) is used; "
                 "bureau and previous-application tables are left out, so no aggregate can include "
                 "events after the application date.")
    return notes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")

    frame = load(args.smoke)
    features = [c for c in frame.columns if c not in ("TARGET", "SK_ID_CURR")]
    notes = leakage_checks(frame, features)
    train, test = train_test_split(frame, test_size=0.2, stratify=frame["TARGET"],
                                   random_state=SEED)
    assert not set(train["SK_ID_CURR"]) & set(test["SK_ID_CURR"]), "applicant in both splits"
    notes.append("Stratified 80/20 split by applicant; no applicant appears in both parts.")

    categorical = [c for c in features if not pd.api.types.is_numeric_dtype(frame[c])]
    numeric = [c for c in features if c not in categorical]
    baseline = Pipeline([
        ("prep", ColumnTransformer([
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")),
                              ("scale", StandardScaler())]), numeric),
            ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                              ("onehot", OneHotEncoder(handle_unknown="ignore"))]), categorical),
        ])),
        ("model", LogisticRegression(max_iter=2_000, class_weight="balanced")),
    ])
    baseline.fit(train[features], train["TARGET"])

    lgb_train = train[features].copy()
    lgb_test = test[features].copy()
    for column in categorical:
        lgb_train[column] = lgb_train[column].astype("category")
        lgb_test[column] = pd.Categorical(lgb_test[column],
                                          categories=lgb_train[column].cat.categories)
    booster = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31,
                                 subsample=0.8, subsample_freq=1, colsample_bytree=0.7,
                                 random_state=SEED, verbose=-1)
    booster.fit(lgb_train, train["TARGET"])

    y = test["TARGET"].to_numpy()
    scores = {"Logistic regression": baseline.predict_proba(test[features])[:, 1],
              "LightGBM": booster.predict_proba(lgb_test)[:, 1]}
    metrics = {name: (roc_auc_score(y, p), average_precision_score(y, p), brier_score_loss(y, p))
               for name, p in scores.items()}

    suffix = "_smoke" if args.smoke else ""
    out_dir = RESULTS if not args.smoke else ROOT / "experiments/risk_benchmark/data"
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(5, 5))
    for name, p in scores.items():
        frac, mean_pred = calibration_curve(y, p, n_bins=10, strategy="quantile")
        plt.plot(mean_pred, frac, marker="o", label=name)
    plt.plot([0, 1], [0, 1], linestyle="--", color="grey", label="perfectly calibrated")
    plt.xlabel("predicted default probability")
    plt.ylabel("observed default rate")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_dir / f"risk_calibration{suffix}.png", dpi=120)
    plt.close()

    sample = lgb_test.sample(min(2_000, len(lgb_test)), random_state=SEED)
    shap_values = shap.TreeExplainer(booster).shap_values(sample)
    shap.summary_plot(shap_values, sample, show=False, max_display=15)
    plt.tight_layout()
    plt.savefig(out_dir / f"risk_shap{suffix}.png", dpi=120)
    plt.close()

    base_rate = float(y.mean())
    for name, (auc, ap, brier) in metrics.items():
        print(f"{name:20} ROC-AUC {auc:.3f}  PR-AUC {ap:.3f}  Brier {brier:.4f}")
    if args.smoke:
        print("smoke run: numbers are meaningless; results page not written")
        return
    (RESULTS / "risk_benchmark.md").write_text(render(len(frame), base_rate, metrics, notes))


def render(n: int, base_rate: float, metrics: dict[str, tuple[float, float, float]],
           notes: list[str]) -> str:
    rows = [f"| {name} | {auc:.3f} | {ap:.3f} | {brier:.4f} |"
            for name, (auc, ap, brier) in metrics.items()]
    return "\n".join([
        "# Credit-risk benchmark (Home Credit Default Risk)",
        "",
        f"{n:,} applications, default rate {base_rate:.1%} in the test split. Generated by "
        "`python experiments/risk_benchmark/run.py`.",
        "",
        "| Model | ROC-AUC | PR-AUC | Brier |",
        "| --- | ---: | ---: | ---: |",
        *rows,
        "",
        "![Calibration](risk_calibration.png) ![SHAP summary](risk_shap.png)",
        "",
        "## Leakage check",
        "",
        *[f"- {note}" for note in notes],
        "",
        WHAT_IT_SHOWS,
    ])


WHAT_IT_SHOWS = """## What this does and doesn't show

- **Population.** Home Credit's applicants are consumer-loan borrowers (mostly individuals,
  many with thin credit files) from Home Credit's own markets. They are not Indian small
  businesses, and the features are personal (age, income, family, bureau scores), not
  business cash flow.
- **Why it doesn't validate scoring KhataIQ businesses.** A model's accuracy only holds on
  data like the data it was trained on. Nothing here measures how bank-statement cash flow
  predicts small-business repayment in India, so no score from this model is shown to
  officers, and KhataIQ's assessments remain human decisions based on evidence.
- **What would be needed.** Repayment outcomes (defaults, delinquencies) for small businesses
  whose statements were analysed *before* the loan, ideally across lenders and regions, with
  consent and a fairness review — and then a time-split evaluation (train on earlier cohorts,
  test on later ones).
"""


if __name__ == "__main__":
    main()
