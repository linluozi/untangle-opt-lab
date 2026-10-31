#!/usr/bin/env python3
"""Print the G3/G4/G5 gate table from the committed benchmark JSONs."""

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    baseline = json.load(open(ROOT / "benchmark" / "baseline.json", encoding="utf-8"))
    optimized = json.load(open(ROOT / "benchmark" / "optimized.json", encoding="utf-8"))

    ratios = []
    print(f"{'scale':>6} {'baseline_ms':>12} {'optimized_ms':>13} {'speedup':>9}")
    for scale in baseline["scales"]:
        b = baseline["results"][str(scale)]["median_s"]
        o = optimized["results"][str(scale)]["median_s"]
        ratio = b / o
        ratios.append(ratio)
        print(f"{scale:>6} {b * 1000:>12.3f} {o * 1000:>13.3f} {ratio:>8.2f}x")

    median = statistics.median(ratios)
    rss_ratio = optimized["peak_rss_kb"] / baseline["peak_rss_kb"]
    print(f"\nmedian speedup: {median:.2f}x  (G3 >= 1.15x: {'PASS' if median >= 1.15 else 'FAIL'})")
    print(f"largest scale:  {ratios[-1]:.2f}x  (G4 >= 0.95x: {'PASS' if ratios[-1] >= 0.95 else 'FAIL'})")
    print(f"peak RSS ratio: {rss_ratio:.3f}x (G5 <= 1.10x: {'PASS' if rss_ratio <= 1.10 else 'FAIL'})")


if __name__ == "__main__":
    main()
