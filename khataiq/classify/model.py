"""The label model: TF-IDF over character n-grams + logistic regression.

It only sees rows the rules didn't label. Its input is one string per row:
    "<DR|CR> AMT<digits of the rupee amount> <normalized narration>"
so direction and order of magnitude are features alongside the narration's character n-grams.
A prediction below CONFIDENCE_FLOOR becomes 'other': a low-confidence guess is worse than an
honest "don't know" (and a human can relabel either).

Saved with joblib under models/label/<version>/ next to a card.json describing the training
data, date and measured macro-F1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from khataiq.config import get_settings

CONFIDENCE_FLOOR = 0.6
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "label" / "v1"


def features(narration_norm: str, direction: str, amount_paise: int) -> str:
    side = "CR" if direction == "credit" else "DR"
    return f"{side} AMT{len(str(amount_paise // 100))} {narration_norm}"


def build_pipeline() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2,
                                  max_features=30_000, sublinear_tf=True)),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=2_000, C=4.0)),
    ])


@dataclass(frozen=True)
class Prediction:
    label: str
    confidence: float  # probability of the predicted class; not money


@dataclass
class LabelModel:
    version: str
    pipeline: Pipeline
    card: dict[str, Any]

    def predict(self, rows: list[tuple[str, str, int]]) -> list[Prediction]:
        """rows: (narration_norm, direction, amount_paise)."""
        if not rows:
            return []
        texts = [features(*row) for row in rows]
        probabilities = self.pipeline.predict_proba(texts)
        classes = list(self.pipeline.classes_)
        result = []
        for probs in probabilities:
            best = int(probs.argmax())
            confidence = float(probs[best])
            label = classes[best] if confidence >= CONFIDENCE_FLOOR else "other"
            result.append(Prediction(label, round(confidence, 4)))
        return result


def save(model: LabelModel, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(model.pipeline, directory / "model.joblib", compress=3)
    (directory / "card.json").write_text(json.dumps(model.card, indent=1) + "\n")


def load(directory: Path) -> LabelModel:
    card = json.loads((directory / "card.json").read_text())
    pipeline = joblib.load(directory / "model.joblib")  # our own artifact, never user input
    return LabelModel(card["version"], pipeline, card)


@lru_cache
def get_model() -> LabelModel | None:
    """The deployed model, or None if no artifact exists (rules still label)."""
    configured = get_settings().label_model_dir
    directory = Path(configured) if configured else DEFAULT_MODEL_DIR
    if not (directory / "model.joblib").is_file():
        return None
    return load(directory)
