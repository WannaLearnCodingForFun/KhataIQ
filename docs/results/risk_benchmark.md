# Credit-risk benchmark (Home Credit Default Risk)

**Status: not run yet.** The dataset needs a Kaggle account and its licence doesn't allow redistribution, so it isn't in the repository or the build environment. The code is complete and checked end to end on random data (`run.py --smoke`); running it on the real file replaces this page with the measured numbers. No numbers are shown here until then — the smoke run's numbers mean nothing.

To run it: follow `experiments/risk_benchmark/README.md` (download `application_train.csv`), then `python experiments/risk_benchmark/run.py`.

## What the run produces

- Logistic regression (median imputation, scaling, one-hot) and LightGBM, stratified 80/20 split by applicant, fixed seed.
- ROC-AUC, PR-AUC and Brier score on the held-out 20%, a calibration curve for both models and a SHAP summary for LightGBM.

## Leakage check (performed by the script)

- `SK_ID_CURR` (an id) and `TARGET` are excluded from the features.
- The script stops if any numeric feature correlates with the target at 0.99 or more.
- Only `application_train.csv` (information known at application time) is used; bureau and previous-application tables are left out, so no aggregate can include events after the application date.
- It asserts that no applicant appears in both the training and test splits.

## What this does and doesn't show

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
