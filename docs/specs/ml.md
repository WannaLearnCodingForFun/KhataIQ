# ML spec

ML in KhataIQ is supporting. It never writes evidence, never approves anything, and every model result
in the UI shows its version and its measured error.

## Labels (`khataiq/classify/`)
Label set: `sales`, `supplier_payment`, `rent`, `salary_paid`, `emi`, `loan_in`, `utilities`,
`cash_deposit`, `cash_withdrawal`, `tax`, `bank_charges`, `personal`, `transfer`, `refund`, `other`.

1. **Rules first** (`rules.py`): ordered list of `(rule_id, version, pattern on narration_norm, direction,
   label)`. First match wins. Stored with `method='rule'`.
2. **Model** (`model.py`) for rows rules didn't label: scikit-learn `TfidfVectorizer(char_wb, 2–5)` +
   `LogisticRegression(class_weight='balanced')`. Saved with `joblib` under `models/label/<version>/`
   with a `card.json` (training data, date, macro-F1). Stored with `method='model'` and `confidence`.
   Rows with confidence < 0.6 get label `other`.
3. **Transformer (optional)**: only if a small multilingual model (e.g. a MiniLM-class encoder) beats
   the baseline macro-F1 by ≥ 3 points on the held-out set. Otherwise document the result and skip it.
4. Human labels (`PATCH /transactions/{id}/label`) always win.

## Forecast (`experiments/forecast/`)
- Target: monthly net business inflow, 1–3 months ahead.
- Baselines: last value, seasonal naive. Model: LightGBM on lag features (1, 2, 3, 12-month where
  available), month-of-year, business type.
- Rolling-origin evaluation; metric MAPE and MAE in paise. Track runs in MLflow (local file store).
- If the model doesn't beat seasonal naive, the app shows no forecast. Write it up either way.

## Risk benchmark (`experiments/risk_benchmark/`)
- Data: Home Credit Default Risk (Kaggle). Repo holds download instructions and code, never the data.
- Models: logistic regression baseline, LightGBM. Leakage check documented. Metrics: ROC-AUC, PR-AUC,
  Brier score, calibration curve, SHAP summary.
- `docs/results/risk_benchmark.md` must include: what population this is, why it doesn't validate
  scoring for Indian small businesses, and what data would be needed to do that.
- The app does not show a score from this model to officers.
