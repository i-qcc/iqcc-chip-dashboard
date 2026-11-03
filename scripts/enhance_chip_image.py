"""Enhance a chip photo so fine features (bumps, lines, pads) stand out.

Usage:
    uv run --with opencv-python-headless scripts/enhance_chip_image.py <raw image> <backend>

Writes ``app/static/chips/<backend>.jpg``, which the dashboard shows for that
backend automatically.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

OUT_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "chips"
MAX_SIDE = 640


def enhance(img: np.ndarray) -> np.ndarray:
    """Local-contrast boost (CLAHE on lightness) followed by an unsharp mask."""
    img = cv2.fastNlMeansDenoisingColored(img, None, 2, 2, 5, 15)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    lightness = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8)).apply(lightness)
    img = cv2.cvtColor(cv2.merge((lightness, a, b)), cv2.COLOR_LAB2BGR)
    blur = cv2.GaussianBlur(img, (0, 0), 2.0)
    return cv2.addWeighted(img, 1.8, blur, -0.8, 0)


def main(raw_path: str, backend: str) -> None:
    img = cv2.imread(raw_path)
    if img is None:
        raise SystemExit(f"Cannot read image: {raw_path}")
    img = enhance(img)
    scale = MAX_SIDE / max(img.shape[:2])
    if scale < 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{backend.lower()}.jpg"
    cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"Wrote {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
