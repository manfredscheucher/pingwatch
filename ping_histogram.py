#!/usr/bin/env python3
"""
Reads a ping_monitor log and creates a histogram of events grouped by hour.

Events:
- S  (suspended):        black bars
- RT (router timeout):   purple bars
- RO (router outlier):   pink bars
- DT (DNS timeout):      red bars
- DO (DNS outlier):      orange bars

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

EVENTS = ["S", "RT", "RO", "DT", "DO"]


def parse_log(log_path: str):
    counts = {k: defaultdict(int) for k in EVENTS}
    min_hour, max_hour = 23, 0

    line_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(S|RT|RO|DT|DO)$")

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
        return {k: {} for k in EVENTS}, 0, 23

    return {k: dict(v) for k, v in counts.items()}, min_hour, max_hour


def make_histogram(counts: dict, min_hour: int, max_hour: int, out_path: str,
                   router: str = "", dns: str = "", show_outliers: bool = False):
    hours = list(range(min_hour, max_hour + 1))
    if not hours:
        print("No data to plot.")
        return

    s_vals  = [counts["S"].get(h, 0)  for h in hours]
    rt_vals = [counts["RT"].get(h, 0) for h in hours]
    ro_vals = [counts["RO"].get(h, 0) for h in hours]
    dt_vals = [counts["DT"].get(h, 0) for h in hours]
    do_vals = [counts["DO"].get(h, 0) for h in hours]

    x = np.arange(len(hours))

    if show_outliers:
        bar_width = 0.16
        bar_groups = [
            (s_vals,  "#1a1a1a", "S  – Suspended",          -2),
            (rt_vals, "#8e44ad", "RT – Router timeout",      -1),
            (ro_vals, "#ff69b4", "RO – Router IQR outlier",   0),
            (dt_vals, "#e74c3c", "DT – DNS timeout",          1),
            (do_vals, "#e67e22", "DO – DNS IQR outlier",      2),
        ]
    else:
        bar_width = 0.25
        bar_groups = [
            (s_vals,  "#1a1a1a", "S  – Suspended",      -1),
            (rt_vals, "#8e44ad", "RT – Router timeout",   0),
            (dt_vals, "#e74c3c", "DT – DNS timeout",      1),
        ]

    fig, ax = plt.subplots(figsize=(max(8, len(hours) * 0.9), 7))

    for vals, color, label, offset in bar_groups:
        bars = ax.bar(x + offset * bar_width, vals, bar_width,
                      label=label if sum(vals) > 0 else None,
                      color=color, alpha=0.85,
                      edgecolor="white", linewidth=0.5)
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.text(bar.get_x() + bar.get_width() / 2., h + 0.15,
                        str(int(h)), ha="center", va="bottom", fontsize=7, color="#333")

    ip_info = ""
    if router or dns:
        parts = []
        if router: parts.append(f"Router: {router}")
        if dns:    parts.append(f"DNS: {dns}")
        ip_info = "\n" + "   |   ".join(parts)

    ax.set_xlabel("Hour of day", fontsize=12)
    ax.set_ylabel("Number of events", fontsize=12)
    all_vals = s_vals + rt_vals + dt_vals
    label_map = [
        (s_vals,  "S",  "suspended"),
        (rt_vals, "RT", "router-timeout"),
        (dt_vals, "DT", "dns-timeout"),
    ]
    if show_outliers:
        all_vals += ro_vals + do_vals
        label_map += [
            (ro_vals, "RO", "router-outlier"),
            (do_vals, "DO", "dns-outlier"),
        ]
    summary = "   ".join(
        f"{tag}={sum(vals)} {name}"
        for vals, tag, name in label_map
        if sum(vals) > 0
    )

    ax.set_title(
        f"Network event histogram by hour  "
        f"({hours[0]:02d}:00 – {hours[-1]:02d}:59){ip_info}\n{summary}",
        fontsize=12,
    )
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h:02d}:00" for h in hours], rotation=45, ha="right", fontsize=9)
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.set_ylim(0, max(max(all_vals), 1) * 1.2)
    ax.legend(fontsize=10, loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"Histogram saved to: {out_path}")
    print(f"Total: S={sum(s_vals)}, RT={sum(rt_vals)}, RO={sum(ro_vals)}, "
          f"DT={sum(dt_vals)}, DO={sum(do_vals)}")


def print_summary(counts: dict, min_hour: int, max_hour: int):
    hours = list(range(min_hour, max_hour + 1))
    if not hours:
        print("No events found in log.")
        return
    print(f"\n{'Hour':>6}  {'S':>5}  {'RT':>6}  {'RO':>6}  {'DT':>6}  {'DO':>6}")
    print("-" * 42)
    for h in hours:
        print(f"  {h:02d}:00"
              f"  {counts['S'].get(h, 0):>5}"
              f"  {counts['RT'].get(h, 0):>6}"
              f"  {counts['RO'].get(h, 0):>6}"
              f"  {counts['DT'].get(h, 0):>6}"
              f"  {counts['DO'].get(h, 0):>6}")
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
    parser.add_argument("--outliers", action="store_true", default=False,
                        help="Also plot RO and DO outlier bars (default: hidden)")
    args = parser.parse_args()

    log_path = args.log
    out_path = args.out or os.path.join(os.path.dirname(os.path.abspath(log_path)), "histogram.png")

    print(f"Reading log: {log_path}")
    counts, min_hour, max_hour = parse_log(log_path)
    print_summary(counts, min_hour, max_hour)
    make_histogram(counts, min_hour, max_hour, out_path,
                   router=args.router, dns=args.dns, show_outliers=args.outliers)


if __name__ == "__main__":
    main()
