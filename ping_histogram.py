#!/usr/bin/env python3
"""
Reads a ping_monitor log and creates a histogram of events grouped by hour.

Events:
- P (suspended):       black bars
- A (router timeout):  purple bars
- B (DNS timeout):     red bars
- C (DNS high-lat):    orange bars
- D (DNS IQR outlier): yellow bars

Only the hour range that actually contains data is shown.
Usage: python3 ping_histogram.py LOG_FILE [--out OUTPUT_PNG]
"""

import argparse
import re
from collections import defaultdict
from datetime import datetime
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def parse_log(log_path: str):
    """
    Parses log lines: "2026-04-21 14:32:17 P|A|B|C|D"
    Returns five dicts (hour -> count) for P, A, B, C, D,
    plus the min and max hour seen.
    """
    counts = {k: defaultdict(int) for k in "PABCD"}
    min_hour, max_hour = 23, 0

    line_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+([PABCD])$")

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
                hour  = ts.hour
                event = m.group(2)
                counts[event][hour] += 1
                if hour < min_hour:
                    min_hour = hour
                if hour > max_hour:
                    max_hour = hour

    except FileNotFoundError:
        print(f"Log file not found: {log_path}")
        return {k: {} for k in "PABCD"}, 0, 23

    return {k: dict(v) for k, v in counts.items()}, min_hour, max_hour


def make_histogram(counts: dict, min_hour: int, max_hour: int, out_path: str,
                   router: str = "", dns: str = ""):
    hours = list(range(min_hour, max_hour + 1))
    if not hours:
        print("No data to plot.")
        return

    p_vals = [counts["P"].get(h, 0) for h in hours]
    a_vals = [counts["A"].get(h, 0) for h in hours]
    b_vals = [counts["B"].get(h, 0) for h in hours]
    d_vals = [counts["D"].get(h, 0) for h in hours]
    c_vals = [counts["C"].get(h, 0) for h in hours]

    x         = np.arange(len(hours))
    bar_width  = 0.16
    offsets    = [-2, -1, 0, 1, 2]

    fig, ax = plt.subplots(figsize=(max(8, len(hours) * 0.9), 7))

    bar_groups = [
        (p_vals, "#1a1a1a", "P – Suspended",              offsets[0]),
        (a_vals, "#8e44ad", "A – Router timeout",          offsets[1]),
        (b_vals, "#e74c3c", "B – DNS timeout",             offsets[2]),
        (c_vals, "#e67e22", "C – DNS high latency >100ms", offsets[3]),
        (d_vals, "#f1c40f", "D – DNS IQR outlier",         offsets[4]),
    ]

    for vals, color, label, offset in bar_groups:
        bars = ax.bar(x + offset * bar_width, vals, bar_width,
                      label=label, color=color, alpha=0.85,
                      edgecolor="white", linewidth=0.5)
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.text(bar.get_x() + bar.get_width() / 2., h + 0.15,
                        str(int(h)), ha="center", va="bottom", fontsize=7, color="#333")

    ax.set_xlabel("Hour of day", fontsize=12)
    ax.set_ylabel("Number of events", fontsize=12)
    ip_info = ""
    if router or dns:
        parts = []
        if router:
            parts.append(f"Router: {router}")
        if dns:
            parts.append(f"DNS: {dns}")
        ip_info = "\n" + "   |   ".join(parts)

    ax.set_title(
        f"Network event histogram by hour  "
        f"({hours[0]:02d}:00 – {hours[-1]:02d}:59){ip_info}\n"
        f"P={sum(p_vals)} suspended   A={sum(a_vals)} router   "
        f"B={sum(b_vals)} DNS   C={sum(c_vals)} high-latency   D={sum(d_vals)} outlier",
        fontsize=13,
    )
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h:02d}:00" for h in hours], rotation=45, ha="right", fontsize=9)
    ax.yaxis.get_major_locator().set_params(integer=True)
    all_vals = p_vals + a_vals + b_vals + d_vals + c_vals
    ax.set_ylim(0, max(max(all_vals), 1) * 1.2)
    ax.legend(fontsize=10, loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"Histogram saved to: {out_path}")
    print(f"Total: P={sum(p_vals)} suspended, A={sum(a_vals)} router, "
          f"B={sum(b_vals)} DNS, C={sum(c_vals)} high-latency, D={sum(d_vals)} outlier")


def print_summary(counts: dict, min_hour: int, max_hour: int):
    hours = list(range(min_hour, max_hour + 1))
    if not hours:
        print("No events found in log.")
        return
    print(f"\n{'Hour':>6}  {'P suspend':>10}  {'A router':>9}  {'B DNS':>7}  {'C high-lat':>11}  {'D outlier':>10}")
    print("-" * 65)
    for h in hours:
        p = counts["P"].get(h, 0)
        a = counts["A"].get(h, 0)
        b = counts["B"].get(h, 0)
        c = counts["C"].get(h, 0)
        d = counts["D"].get(h, 0)
        print(f"  {h:02d}:00  {p:>10}  {a:>9}  {b:>7}  {c:>11}  {d:>10}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Create ping event histogram from log")
    parser.add_argument("log", type=str, help="Log file to read")
    parser.add_argument("--out", "-o", type=str, default=None,
                        help="Output PNG path (default: <log_dir>/histogram.png)")
    parser.add_argument("--router", type=str, default="",
                        help="Router IP to show in chart (e.g. 192.168.0.1)")
    parser.add_argument("--dns", type=str, default="",
                        help="DNS IP to show in chart (e.g. 8.8.8.8)")
    args = parser.parse_args()

    log_path = args.log
    out_path = args.out or os.path.join(os.path.dirname(os.path.abspath(log_path)), "histogram.png")

    print(f"Reading log: {log_path}")
    counts, min_hour, max_hour = parse_log(log_path)
    print_summary(counts, min_hour, max_hour)
    make_histogram(counts, min_hour, max_hour, out_path, router=args.router, dns=args.dns)


if __name__ == "__main__":
    main()
