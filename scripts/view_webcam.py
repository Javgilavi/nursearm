#!/usr/bin/env python
"""Minimal webcam viewer for debugging camera access outside Cheese/GStreamer."""

from __future__ import annotations

import argparse

import cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=0, help="VideoCapture index to open")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cap = cv2.VideoCapture(args.index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        raise RuntimeError(f"failed to open webcam index {args.index}")

    print(f"Viewing webcam index {args.index}. Press q to quit.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                raise RuntimeError(f"failed to read frame from webcam index {args.index}")
            cv2.imshow("Webcam Viewer", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
