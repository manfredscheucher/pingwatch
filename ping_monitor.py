#!/usr/bin/env python3
"""
Ping monitor:
  A = router (192.168.0.1) timeout          → rot
  B = DNS (8.8.8.8) timeout                 → orange
  C = DNS ping > 100ms (aber erreichbar)    → gelb

Logik: A impliziert B impliziert C (A ist am kritischsten).
Log: "<timestamp> A|B|C" — nur den schwersten Fehler pro Runde.
Usage: python3 ping_monitor.py [-t INTERVAL] [-l LOGFILE]
"""

import argparse
import subprocess
import re
import sys
import time
import os
from datetime import datetime

HIGH_LATENCY_MS = 100
FLUSH_INTERVAL  = 60  # seconds

# ANSI colors
RED    = "\033[31m"
ORANGE = "\033[33m"
YELLOW = "\033[93m"
RESET  = "\033[0m"


def ping_host(host: str) -> tuple[bool, float | None]:
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", host],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            m = re.search(r"time[=<]([\d.]+)\s*ms", result.stdout)
            return True, float(m.group(1)) if m else None
        return False, None
    except Exception:
        return False, None


def print_status(now: datetime, router: str, router_ok: bool, router_ms: float | None,
                 dns: str, dns_ok: bool, dns_ms: float | None):
    def fmt(ok, ms):
        if not ok:
            return "TIMEOUT"
        return f"{ms:.1f}ms" if ms is not None else "OK"

    ts = now.strftime("%H:%M:%S")
    line = (f"\r[{ts}]  "
            f"Router({router})={fmt(router_ok, router_ms)}  |  "
            f"DNS({dns})={fmt(dns_ok, dns_ms)}   ")
    sys.stdout.write(line)
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Ping monitor — tracks router & DNS health")
    parser.add_argument("-t", "--interval", type=float, default=1.0,
                        help="Ping interval in seconds (default: 1)")
    parser.add_argument("--router", type=str, default="192.168.0.1",
                        help="Router IP to monitor (default: 192.168.0.1)")
    parser.add_argument("--dns", type=str, default="8.8.8.8",
                        help="DNS server IP to monitor (default: 8.8.8.8)")
    default_log = f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    parser.add_argument("-l", "--log", type=str, default=default_log,
                        help="Log file (default: log_<timestamp>.txt)")
    args = parser.parse_args()

    interval  = args.interval
    log_path  = args.log
    router    = args.router
    dns       = args.dns
    last_flush = time.time()

    event_colors = {"A": RED, "B": ORANGE, "C": YELLOW}
    event_desc   = {
        "A": f"router timeout     ({router})",
        "B": f"DNS timeout        ({dns})",
        "C": f"DNS high latency   ({dns} >{HIGH_LATENCY_MS}ms)",
    }

    print(f"Ping monitor  |  interval={interval}s  |  log={log_path}")
    print(f"  A = {event_desc['A']}")
    print(f"  B = {event_desc['B']}")
    print(f"  C = {event_desc['C']}")
    print("-" * 60)

    log_file = open(log_path, "a", buffering=1)

    def flush_log():
        log_file.flush()
        os.fsync(log_file.fileno())

    try:
        while True:
            now = datetime.now()
            ts_str = now.strftime("%Y-%m-%d %H:%M:%S")

            router_ok, router_ms = ping_host(router)
            dns_ok,    dns_ms    = ping_host(dns)

            # Determine worst event (A > B > C, mutually exclusive in log)
            event = None
            if not router_ok:
                event = "A"
            elif not dns_ok:
                event = "B"
            elif dns_ms is not None and dns_ms > HIGH_LATENCY_MS:
                event = "C"

            if event:
                color = event_colors[event]
                desc  = event_desc[event]
                line  = f"{ts_str} {event}"
                extra = f"  ({dns_ms:.1f}ms)" if event == "C" else ""
                sys.stdout.write(f"\r{color}{line}  — {desc}{extra}{RESET}\n")
                sys.stdout.flush()
                log_file.write(line + "\n")

            print_status(now, router, router_ok, router_ms, dns, dns_ok, dns_ms)

            if time.time() - last_flush >= FLUSH_INTERVAL:
                flush_log()
                last_flush = time.time()

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nStopping monitor...")
        flush_log()
        log_file.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
