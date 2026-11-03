# Risk benchmark (Home Credit Default Risk)

A credit-risk modelling exercise on a **public dataset from a different population**. It is here to
show modelling and evaluation practice. **Its scores are never shown to officers and are not a score
for KhataIQ businesses** (see `docs/results/risk_benchmark.md`, "What this does and doesn't show").

## Get the data (not in the repo)

The data is licensed for the competition and can't be redistributed.

1. Create a Kaggle account, accept the rules of the *Home Credit Default Risk* competition, and set up
   an API token (`~/.kaggle/kaggle.json`).
2. Download and unzip `application_train.csv` into `experiments/risk_benchmark/data/` (git-ignored):

```bash
pip install kaggle
```

```bash
kaggle competitions download -c home-credit-default-risk -f application_train.csv -p experiments/risk_benchmark/data
```

```bash
unzip experiments/risk_benchmark/data/application_train.csv.zip -d experiments/risk_benchmark/data
```

## Run

```bash
python experiments/risk_benchmark/run.py
```

It writes `docs/results/risk_benchmark.md` and two plots (calibration curve, SHAP summary) next to it.
`python experiments/risk_benchmark/run.py --smoke` runs the same code on a few hundred random rows to
check the pipeline works; its numbers mean nothing and it doesn't overwrite the results page.
