#!/usr/bin/env python3
"""
Reads a ping_monitor log and creates a histogram of events grouped by hour.

Events:
- S  (suspended):        black bars
- RT (router timeout):   purple bars
- RO (router outlier):   pink bars
- DT (DNS timeout):      red bars
- DO (DNS outlier):      orange bars

Usage: python3 ping_histogram.py LOG_FILE [--out OUTPUT_PNG] [--outliers] [--per-day]
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
LINE_PAT = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):\d{2}:\d{2}\s+(S|RT|RO|DT|DO)$")


def parse_log(log_path: str):
    """
    Returns a dict: date_str -> {event -> {hour -> count}}
    and also a combined entry under key None for the overall view.
    """
    by_day = {}  # "2026-04-22" -> {event -> {hour -> count}}

    try:
        with open(log_path, "r") as f:
            for line in f:
                m = LINE_PAT.match(line.strip())
                if not m:
                    continue
                date_str, hour_str, event = m.group(1), m.group(2), m.group(3)
                hour = int(hour_str)
                if date_str not in by_day:
                    by_day[date_str] = {k: defaultdict(int) for k in EVENTS}
                by_day[date_str][event][hour] += 1

    except FileNotFoundError:
        print(f"Log file not found: {log_path}")
        return {}

    # Convert inner defaultdicts to plain dicts
    return {
        date: {ev: dict(hours) for ev, hours in events.items()}
        for date, events in sorted(by_day.items())
    }


def make_histogram(date_str: str, counts: dict, out_path: str,
                   router: str = "", dns: str = "", show_outliers: bool = False):
    hours_with_data = set()
    for ev in EVENTS:
        hours_with_data.update(counts[ev].keys())
    if not hours_with_data:
        print(f"No data for {date_str}, skipping.")
        return

    min_hour = min(hours_with_data)
    max_hour = max(hours_with_data)
    hours = list(range(min_hour, max_hour + 1))

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
        ip_info = "   |   ".join(parts) + "\n"

    label_map = [
        (s_vals,  "S",  "suspended"),
        (rt_vals, "RT", "router-timeout"),
        (dt_vals, "DT", "dns-timeout"),
    ]
    if show_outliers:
        label_map += [
            (ro_vals, "RO", "router-outlier"),
            (do_vals, "DO", "dns-outlier"),
        ]
    summary = "   ".join(
        f"{tag}={sum(vals)} {name}"
        for vals, tag, name in label_map
        if sum(vals) > 0
    )

    all_vals = s_vals + rt_vals + dt_vals
    if show_outliers:
        all_vals += ro_vals + do_vals

    ax.set_title(
        f"{ip_info}{date_str}  —  {hours[0]:02d}:00 – {hours[-1]:02d}:59\n{summary}",
        fontsize=12,
    )
    ax.set_xlabel("Hour of day", fontsize=12)
    ax.set_ylabel("Number of events", fontsize=12)
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
    print(f"  {date_str} → {out_path}")


def make_histogram_combined(by_day: dict, out_path: str,
                            router: str = "", dns: str = "", show_outliers: bool = False):
    """Combined plot with (date, hour) pairs on X-axis, preserving per-day order."""
    # Build ordered list of (date, hour) slots
    slots = []
    for date_str, counts in sorted(by_day.items()):
        hours_with_data = set()
        for ev in EVENTS:
            hours_with_data.update(counts[ev].keys())
        if not hours_with_data:
            continue
        for h in range(min(hours_with_data), max(hours_with_data) + 1):
            slots.append((date_str, h))

    if not slots:
        print("No data to plot.")
        return

    def get_val(ev, date_str, hour):
        return by_day[date_str][ev].get(hour, 0)

    s_vals  = [get_val("S",  d, h) for d, h in slots]
    rt_vals = [get_val("RT", d, h) for d, h in slots]
    ro_vals = [get_val("RO", d, h) for d, h in slots]
    dt_vals = [get_val("DT", d, h) for d, h in slots]
    do_vals = [get_val("DO", d, h) for d, h in slots]

    x = np.arange(len(slots))

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

    fig, ax = plt.subplots(figsize=(max(8, len(slots) * 0.6), 7))

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

    # X-axis labels: show date only at first hour of each day
    tick_labels = []
    for i, (date_str, hour) in enumerate(slots):
        if i == 0 or slots[i - 1][0] != date_str:
            tick_labels.append(f"{date_str}\n{hour:02d}:00")
        else:
            tick_labels.append(f"{hour:02d}:00")

    # Draw vertical line between days
    for i in range(1, len(slots)):
        if slots[i][0] != slots[i - 1][0]:
            ax.axvline(x=i - 0.5, color="#aaa", linestyle="--", linewidth=0.8)

    ip_info = ""
    if router or dns:
        parts = []
        if router: parts.append(f"Router: {router}")
        if dns:    parts.append(f"DNS: {dns}")
        ip_info = "   |   ".join(parts) + "\n"

    all_dates = sorted(by_day.keys())
    label_map = [
        (s_vals,  "S",  "suspended"),
        (rt_vals, "RT", "router-timeout"),
        (dt_vals, "DT", "dns-timeout"),
    ]
    if show_outliers:
        label_map += [
            (ro_vals, "RO", "router-outlier"),
            (do_vals, "DO", "dns-outlier"),
        ]
    summary = "   ".join(
        f"{tag}={sum(vals)} {name}"
        for vals, tag, name in label_map
        if sum(vals) > 0
    )

    all_vals = s_vals + rt_vals + dt_vals + (ro_vals + do_vals if show_outliers else [])

    ax.set_title(
        f"{ip_info}{all_dates[0]} – {all_dates[-1]}\n{summary}",
        fontsize=12,
    )
    ax.set_xlabel("Date / Hour", fontsize=12)
    ax.set_ylabel("Number of events", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=8)
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.set_ylim(0, max(max(all_vals), 1) * 1.2)
    ax.legend(fontsize=10, loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"  combined → {out_path}")


def print_summary(by_day: dict):
    for date_str, counts in by_day.items():
        hours_with_data = set()
        for ev in EVENTS:
            hours_with_data.update(counts[ev].keys())
        if not hours_with_data:
            continue
        hours = sorted(hours_with_data)
        print(f"\n{date_str}")
        print(f"  {'Hour':>6}  {'S':>5}  {'RT':>6}  {'RO':>6}  {'DT':>6}  {'DO':>6}")
        print("  " + "-" * 40)
        for h in range(min(hours), max(hours) + 1):
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
    parser.add_argument("--per-day", action="store_true", default=False,
                        help="Create one PNG per day (named histogram_YYYY-MM-DD.png)")
    args = parser.parse_args()

    log_path = args.log
    log_dir  = os.path.dirname(os.path.abspath(log_path))

    print(f"Reading log: {log_path}")
    by_day = parse_log(log_path)
    if not by_day:
        print("No events found.")
        return

    print_summary(by_day)

    kwargs = dict(router=args.router, dns=args.dns, show_outliers=args.outliers)

    if args.per_day:
        for date_str, counts in by_day.items():
            out_path = os.path.join(log_dir, f"histogram_{date_str}.png")
            make_histogram(date_str, counts, out_path, **kwargs)
    else:
        all_dates = sorted(by_day.keys())
        out_path = args.out or os.path.join(log_dir, "histogram.png")
        if len(all_dates) == 1:
            make_histogram(all_dates[0], by_day[all_dates[0]], out_path, **kwargs)
        else:
            make_histogram_combined(by_day, out_path, **kwargs)


if __name__ == "__main__":
    main()
