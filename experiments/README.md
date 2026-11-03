# Experiments

Offline ML experiments. **Nothing here is imported by the app.** Install their extra
dependencies with `pip install -e '.[dev,experiments]'`.

| Folder | What | Result |
| --- | --- | --- |
| `forecast/` | 1–3 month cash-flow forecast: LightGBM vs last-value and seasonal-naive, rolling-origin | `docs/results/forecast.md` |
| `risk_benchmark/` | Credit-risk models on the public Home Credit dataset (a different population) | `docs/results/risk_benchmark.md` |

MLflow runs are tracked in a local SQLite store (`experiments/*/mlflow.db`, git-ignored):
`mlflow ui --backend-store-uri sqlite:///experiments/forecast/mlflow.db`.
