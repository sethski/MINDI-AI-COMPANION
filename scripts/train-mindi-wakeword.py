"""Train a custom openWakeWord model for the phrase 'hey mindi'."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Train MINDI wake word ONNX model")
    parser.add_argument(
        "--output",
        default="apps/desktop/public/wakeword/mindi.onnx",
        help="Output ONNX path",
    )
    args = parser.parse_args()

    try:
        from openwakeword.train import train_model
    except ImportError as exc:
        raise SystemExit(
            "openwakeword is required. Install with: pip install openwakeword"
        ) from exc

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    train_model(
        target_phrase="hey mindi",
        model_name="mindi",
        output_dir=str(output.parent),
    )
    print(f"Trained wake model written under {output.parent}")


if __name__ == "__main__":
    main()
