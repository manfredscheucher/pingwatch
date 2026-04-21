#!/usr/bin/env python3
"""
Reads ping_log.txt and creates a histogram of outages/high-latency events
grouped by hour of day.

- A (router 192.168.0.1): red bars   — outages
- B (DNS 8.8.8.8):         blue bars  — outages
- C (DNS high latency):    orange bars — DNS pings > 100ms

Output: histogram.png (next to the log file)
Usage: python3 ping_histogram.py [--log LOG_FILE] [--out OUTPUT_PNG]
"""

import argparse
import re
from collections import defaultdict
from datetime import datetime
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


def parse_log(log_path: str):
    """
    Parses compact log format: "2026-04-21 14:32:17 A|B|C"
    Returns three dicts: hour -> count for A, B, C events.
    """
    a_counts: dict[int, int] = defaultdict(int)
    b_counts: dict[int, int] = defaultdict(int)
    c_counts: dict[int, int] = defaultdict(int)

    line_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+([ABC])$")

    try:
        with open(log_path, "r") as f:
            for line in f:
                m = line_pattern.match(line.strip())
                if not m:
                    continue
                try:
                    ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                hour = ts.hour
                event = m.group(2)
                if event == "A":
                    a_counts[hour] += 1
                elif event == "B":
                    b_counts[hour] += 1
                elif event == "C":
                    c_counts[hour] += 1

    except FileNotFoundError:
        print(f"Log file not found: {log_path}")
        return {}, {}, {}

    return dict(a_counts), dict(b_counts), dict(c_counts)


def make_histogram(a_outages, b_outages, c_high_latency, out_path: str):
    hours = list(range(24))
    a_vals = [a_outages.get(h, 0) for h in hours]
    b_vals = [b_outages.get(h, 0) for h in hours]
    c_vals = [c_high_latency.get(h, 0) for h in hours]

    total_events = sum(a_vals) + sum(b_vals) + sum(c_vals)

    x = np.arange(len(hours))
    bar_width = 0.26

    fig, ax = plt.subplots(figsize=(16, 7))

    bars_a = ax.bar(x - bar_width, a_vals, bar_width, label="A – Router timeout (192.168.0.1)",
                    color="#e74c3c", alpha=0.85, edgecolor="white", linewidth=0.5)
    bars_b = ax.bar(x,             b_vals, bar_width, label="B – DNS timeout (8.8.8.8)",
                    color="#e67e22", alpha=0.85, edgecolor="white", linewidth=0.5)
    bars_c = ax.bar(x + bar_width, c_vals, bar_width, label="C – DNS high latency >100ms",
                    color="#f1c40f", alpha=0.85, edgecolor="white", linewidth=0.5)

    # Value labels on top of bars
    for bars in (bars_a, bars_b, bars_c):
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.text(bar.get_x() + bar.get_width() / 2., h + 0.15,
                        str(int(h)), ha="center", va="bottom", fontsize=7, color="#333")

    ax.set_xlabel("Hour of day", fontsize=12)
    ax.set_ylabel("Number of events", fontsize=12)
    ax.set_title(
        f"Network outage & high-latency histogram by hour\n"
        f"A={sum(a_vals)} router timeouts   B={sum(b_vals)} DNS timeouts   "
        f"C={sum(c_vals)} DNS high-latency",
        fontsize=13,
    )
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h:02d}:00" for h in hours], rotation=45, ha="right", fontsize=9)
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.set_ylim(0, max(max(a_vals), max(b_vals), max(c_vals), 1) * 1.2)
    ax.legend(fontsize=10, loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"Histogram saved to: {out_path}")
    print(f"Total: A={sum(a_vals)} router timeouts, B={sum(b_vals)} DNS timeouts, "
          f"C={sum(c_vals)} DNS high-latency events")


def print_summary(a_outages, b_outages, c_high_latency):
    all_hours = sorted(set(list(a_outages) + list(b_outages) + list(c_high_latency)))
    if not all_hours:
        print("No events found in log.")
        return
    print(f"\n{'Hour':>6}  {'A outages':>10}  {'B outages':>10}  {'C high-lat':>11}")
    print("-" * 44)
    for h in all_hours:
        a = a_outages.get(h, 0)
        b = b_outages.get(h, 0)
        c = c_high_latency.get(h, 0)
        print(f"  {h:02d}:00  {a:>10}  {b:>10}  {c:>11}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Create ping outage histogram from log")
    parser.add_argument("log", type=str, help="Log file to read")
    parser.add_argument("--out", "-o", type=str, default=None,
                        help="Output PNG path (default: <log_dir>/histogram.png)")
    args = parser.parse_args()

    log_path = args.log
    out_path = args.out or os.path.join(os.path.dirname(os.path.abspath(log_path)), "histogram.png")

    print(f"Reading log: {log_path}")
    a_outages, b_outages, c_high_latency = parse_log(log_path)
    print_summary(a_outages, b_outages, c_high_latency)
    make_histogram(a_outages, b_outages, c_high_latency, out_path)


if __name__ == "__main__":
    main()
