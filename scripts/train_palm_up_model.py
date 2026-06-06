#!/usr/bin/env python
"""Train the palm-up classifier from a labeled JSONL dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

from nursearm import config
from nursearm.perception.palm_up_model import MODEL_PATH, evaluate, train_from_jsonl

DEFAULT_DATASET = config.ROOT / "data" / "datasets" / "palm_up_dataset.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--output", default=str(MODEL_PATH))
    parser.add_argument("--epochs", type=int, default=600)
    parser.add_argument("--lr", type=float, default=0.08)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = Path(args.dataset)
    output = Path(args.output)
    model = train_from_jsonl(
        dataset_path=dataset,
        output_path=output,
        epochs=args.epochs,
        lr=args.lr,
    )
    metrics = evaluate(model, dataset)
    print(f"Model saved to {output}")
    print(
        "accuracy={accuracy:.3f} precision={precision:.3f} recall={recall:.3f} samples={samples:.0f}".format(
            **metrics
        )
    )


if __name__ == "__main__":
    main()
