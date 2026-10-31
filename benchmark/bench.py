#!/usr/bin/env python3
"""
Benchmark: parse a wide XML document, then query every distinct child tag once.

The measured unit is the full pipeline (parse + one get_elements() call per tag),
because that is how untangle is used by XML-to-dict style consumers.

Usage:
    python benchmark/bench.py --impl baseline  --out benchmark/baseline.json
    python benchmark/bench.py --impl optimized --out benchmark/optimized.json

Raw per-iteration samples are written to benchmark/raw/<impl>-<scale>-<i>.json.
"""

import argparse
import importlib.util
import json
import os
import platform
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SEED = 20261031
SCALES = [250, 1000, 4000]
WARMUP = 3
REPEAT = 5
UPSTREAM_COMMIT = "8a4740cf5eb54bb4166e4a4986222a89549127f5"


def load_impl(name):
    path = SRC / f"untangle_{name}.py"
    spec = importlib.util.spec_from_file_location(f"untangle_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_xml(n):
    """Wide document: n distinct tags, one child each, plus attributes and text."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?><root>']
    for i in range(n):
        tag = f"tag_{i:05d}"
        parts.append(f'<{tag} id="{i}">value-{i}</{tag}>')
    parts.append("</root>")
    return "".join(parts)


def run_once(module, xml, tags):
    t0 = time.perf_counter()
    doc = module.parse(xml)
    container = doc.root
    found = {tag: container.get_elements(tag) for tag in tags}
    elapsed = time.perf_counter() - t0
    assert len(found) == len(tags)
    assert all(len(v) == 1 for v in found.values())
    return elapsed


def percentile(sorted_values, q):
    """Linear interpolation percentile, q in [0, 100]."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def cpu_model():
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def mem_total_kb():
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--impl", choices=["baseline", "optimized"], required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--raw-dir", default=str(ROOT / "benchmark" / "raw"))
    args = parser.parse_args()

    module = load_impl(args.impl)
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for scale in SCALES:
        xml = make_xml(scale)
        tags = [f"tag_{i:05d}" for i in range(scale)]
        for _ in range(WARMUP):
            run_once(module, xml, tags)

        samples = []
        for i in range(REPEAT):
            seconds = run_once(module, xml, tags)
            samples.append(seconds)
            raw = {
                "impl": args.impl,
                "scale": scale,
                "iteration": i,
                "seconds": seconds,
                "seed": SEED,
                "warmup": WARMUP,
                "repeat": REPEAT,
            }
            with open(raw_dir / f"{args.impl}-{scale}-{i}.json", "w", encoding="utf-8") as fh:
                json.dump(raw, fh, indent=2, sort_keys=True)
                fh.write("\n")

        ordered = sorted(samples)
        median = statistics.median(ordered)
        results[str(scale)] = {
            "median_s": median,
            "p25_s": percentile(ordered, 25),
            "p75_s": percentile(ordered, 75),
            "min_s": ordered[0],
            "max_s": ordered[-1],
            "mean_s": statistics.fmean(ordered),
            "rsd_pct": (statistics.stdev(ordered) / statistics.fmean(ordered) * 100.0)
            if len(ordered) > 1
            else 0.0,
            "samples_s": samples,
        }

    payload = {
        "impl": args.impl,
        "upstream": "stchris/untangle",
        "upstream_commit": UPSTREAM_COMMIT,
        "workload": (
            "parse a wide XML document with N distinct child tags, then call "
            "get_elements(tag) once for every tag"
        ),
        "scales": SCALES,
        "warmup": WARMUP,
        "repeat": REPEAT,
        "seed": SEED,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_model": cpu_model(),
        "cpu_count": os.cpu_count(),
        "mem_total_kb": mem_total_kb(),
        "peak_rss_kb": None,
        "results": results,
        "command": " ".join([sys.executable, "benchmark/bench.py", "--impl", args.impl,
                             "--out", args.out]),
    }

    import resource

    payload["peak_rss_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"{args.impl}:")
    for scale in SCALES:
        r = results[str(scale)]
        print(
            f"  n={scale:5d}  median={r['median_s']*1000:9.3f} ms  "
            f"p25={r['p25_s']*1000:9.3f}  p75={r['p75_s']*1000:9.3f}  "
            f"rsd={r['rsd_pct']:5.2f}%"
        )
    print(f"  peak_rss={payload['peak_rss_kb']/1024:.1f} MiB")


if __name__ == "__main__":
    main()
