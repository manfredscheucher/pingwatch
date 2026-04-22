#!/usr/bin/env python3
"""
Ping monitor:
  P = system was suspended / laptop was asleep  → (logged, no ping)
  A = router (192.168.0.1) timeout              → purple
  B = DNS (8.8.8.8) timeout                     → red
  C = DNS ping > 100ms (but reachable)          → orange
  D = DNS IQR outlier (statistically unusual)   → yellow
  E = Router IQR outlier (statistically unusual)→ pink

Logic: P > A > E > B > D > C
Log: "<timestamp> P|A|B|C|D|E" — only the worst event per round.
Usage: python3 ping_monitor.py [-t INTERVAL] [-l LOGFILE]
"""

import argparse
import math
import subprocess
import re
import sys
import time
import os
import threading
from datetime import datetime

HIGH_LATENCY_MS  = 100
FLUSH_INTERVAL   = 60   # seconds
SUSPEND_THRESHOLD = 3   # multiples of interval
IQR_MIN_SAMPLES  = 30

# ANSI colors
PURPLE = "\033[35m"
PINK   = "\033[95m"
RED    = "\033[31m"
ORANGE = "\033[33m"
YELLOW = "\033[93m"
WHITE  = "\033[97m"
RESET  = "\033[0m"


def detect_router() -> str | None:
    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(["route", "-n", "get", "default"],
                                          text=True, timeout=3)
            m = re.search(r"gateway:\s+([\d.]+)", out)
        else:
            out = subprocess.check_output(["ip", "route", "show", "default"],
                                          text=True, timeout=3)
            m = re.search(r"default via ([\d.]+)", out)
        return m.group(1) if m else None
    except Exception:
        return None


def ping_host(host: str, timeout_s: int = 1) -> tuple[bool, float | None]:
    try:
        # macOS: -W is in milliseconds; Linux: -W is in seconds
        w = str(timeout_s * 1000) if sys.platform == "darwin" else str(timeout_s)
        result = subprocess.run(
            ["ping", "-c", "1", "-W", w, host],
            capture_output=True, text=True, timeout=timeout_s + 1,
        )
        if result.returncode == 0:
            m = re.search(r"time[=<]([\d.]+)\s*ms", result.stdout)
            return True, float(m.group(1)) if m else None
        return False, None
    except Exception:
        return False, None


def freq_stats(freq: dict[int, int]) -> tuple[float, float, float, float, float]:
    """Returns (mean, median, stddev, q1, q3) from a frequency dict (ms -> count)."""
    total = sum(freq.values())
    if total == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    mean = sum(k * v for k, v in freq.items()) / total
    variance = sum(v * (k - mean) ** 2 for k, v in freq.items()) / total
    stddev = math.sqrt(variance)

    sorted_keys = sorted(freq.keys())

    def weighted_percentile(p: float) -> float:
        target = p * total
        cumulative = 0
        for k in sorted_keys:
            cumulative += freq[k]
            if cumulative >= target:
                return float(k)
        return float(sorted_keys[-1])

    return mean, weighted_percentile(0.5), stddev, weighted_percentile(0.25), weighted_percentile(0.75)


def is_iqr_outlier(val: float, q1: float, q3: float, n: int) -> bool:
    if n < IQR_MIN_SAMPLES:
        return False
    iqr = q3 - q1
    return iqr > 0 and (val < q1 - 1.5 * iqr or val > q3 + 1.5 * iqr)


def fmt_stats(avg: float, med: float, sd: float, n: int) -> str:
    if n == 0:
        return ""
    return f"  (avg={avg:5.1f}  med={med:5.1f}  sd={sd:5.1f})"


def print_status(now: datetime, ping_count: int,
                 router_ms: float | None, r_avg: float, r_med: float, r_sd: float, r_n: int,
                 dns_ms: float | None,   d_avg: float, d_med: float, d_sd: float, d_n: int):
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    r = f"{router_ms:6.1f}ms" if router_ms is not None else " TIMEOUT"
    d = f"{dns_ms:6.1f}ms"    if dns_ms    is not None else " TIMEOUT"
    sys.stdout.write(
        f"\r{ts}  ping #{ping_count:>6}"
        f"  router={r}{fmt_stats(r_avg, r_med, r_sd, r_n)}"
        f"  dns={d}{fmt_stats(d_avg, d_med, d_sd, d_n)}   "
    )
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Ping monitor — tracks router & DNS health")
    parser.add_argument("-t", "--interval", type=float, default=1.0,
                        help="Ping interval in seconds (default: 1)")
    default_router = detect_router() or "192.168.0.1"
    parser.add_argument("--router", type=str, default=default_router,
                        help=f"Router IP to monitor (default: auto-detected, currently {default_router})")
    parser.add_argument("--dns", type=str, default="8.8.8.8",
                        help="DNS server IP to monitor (default: 8.8.8.8)")
    default_log = f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    parser.add_argument("-l", "--log", type=str, default=default_log,
                        help="Log file (default: log_<timestamp>.txt)")
    args = parser.parse_args()

    interval   = args.interval
    log_path   = args.log
    router     = args.router
    dns        = args.dns
    last_flush = time.time()

    router_ping_freq: dict[int, int] = {}
    dns_ping_freq:    dict[int, int] = {}

    event_colors = {"P": WHITE, "A": PURPLE, "E": PINK, "B": RED, "C": ORANGE, "D": YELLOW}
    event_desc   = {
        "P": "system suspended      (laptop sleep / pause)",
        "A": f"router timeout        ({router})",
        "E": f"router IQR outlier    ({router})",
        "B": f"DNS timeout           ({dns})",
        "C": f"DNS high latency      ({dns} >{HIGH_LATENCY_MS}ms)",
        "D": f"DNS IQR outlier       ({dns})",
    }

    print(f"Ping monitor  |  interval={interval}s  |  log={log_path}")
    for k in "PABCDE":
        print(f"  {k} = {event_desc[k]}")
    print("-" * 60)

    log_file = open(log_path, "a", buffering=1)

    def flush_log():
        log_file.flush()
        os.fsync(log_file.fileno())

    ping_count    = 0
    event_counter = 0

    def log_event(ts_str: str, event: str, extra: str = ""):
        nonlocal event_counter
        event_counter += 1
        color = event_colors[event]
        desc  = event_desc[event]
        sys.stdout.write(f"{color}{ts_str}  event #{event_counter:>5}  {event}  — {desc}{extra}{RESET}\n")
        sys.stdout.flush()
        log_file.write(f"{ts_str} {event}\n")

    prev_monotonic = time.monotonic()

    try:
        while True:
            deadline = time.monotonic() + interval
            now      = datetime.now()
            ts_str   = now.strftime("%Y-%m-%d %H:%M:%S")

            elapsed = time.monotonic() - prev_monotonic
            if elapsed > interval * SUSPEND_THRESHOLD:
                log_event(ts_str, "P")
                flush_log()
                prev_monotonic = time.monotonic()
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                continue

            prev_monotonic = time.monotonic()
            ping_count += 1

            results = {}
            def _ping(host, key):
                results[key] = ping_host(host)
            threads = [
                threading.Thread(target=_ping, args=(router, "router"), daemon=True),
                threading.Thread(target=_ping, args=(dns,    "dns"),    daemon=True),
            ]
            for t in threads: t.start()
            for t in threads: t.join()

            router_ok, router_ms = results["router"]
            dns_ok,    dns_ms    = results["dns"]

            # Update frequency dicts
            if router_ok and router_ms is not None:
                k = round(router_ms)
                router_ping_freq[k] = router_ping_freq.get(k, 0) + 1
            if dns_ok and dns_ms is not None:
                k = round(dns_ms)
                dns_ping_freq[k] = dns_ping_freq.get(k, 0) + 1

            # Compute stats
            if router_ping_freq:
                r_avg, r_med, r_sd, r_q1, r_q3 = freq_stats(router_ping_freq)
                r_n = sum(router_ping_freq.values())
            else:
                r_avg = r_med = r_sd = r_q1 = r_q3 = 0.0
                r_n = 0

            if dns_ping_freq:
                d_avg, d_med, d_sd, d_q1, d_q3 = freq_stats(dns_ping_freq)
                d_n = sum(dns_ping_freq.values())
            else:
                d_avg = d_med = d_sd = d_q1 = d_q3 = 0.0
                d_n = 0

            # Determine worst event: P > A > E > B > D > C
            # Router and DNS are evaluated independently; worst wins.
            router_event = None
            if not router_ok:
                router_event = "A"
            elif router_ms is not None and is_iqr_outlier(router_ms, r_q1, r_q3, r_n):
                router_event = "E"

            dns_event = None
            if not dns_ok:
                dns_event = "B"
            elif dns_ms is not None and is_iqr_outlier(dns_ms, d_q1, d_q3, d_n):
                dns_event = "D"
            elif dns_ms is not None and dns_ms > HIGH_LATENCY_MS:
                dns_event = "C"

            priority = {"A": 5, "E": 4, "B": 3, "D": 2, "C": 1}
            event = max((e for e in (router_event, dns_event) if e),
                        key=lambda e: priority[e], default=None)

            if event:
                if event in ("E",):
                    extra = f"  ({router_ms:.1f}ms)"
                elif event in ("C", "D"):
                    extra = f"  ({dns_ms:.1f}ms)"
                else:
                    extra = ""
                log_event(ts_str, event, extra)

            print_status(now, ping_count,
                         router_ms, r_avg, r_med, r_sd, r_n,
                         dns_ms,    d_avg, d_med, d_sd, d_n)

            if time.time() - last_flush >= FLUSH_INTERVAL:
                flush_log()
                last_flush = time.time()

            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        print("\nStopping monitor...")
        flush_log()
        log_file.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
