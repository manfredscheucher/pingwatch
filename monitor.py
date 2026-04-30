#!/usr/bin/env python3
"""
Ping monitor:
  S  = system suspended (laptop sleep)          → red
  LT = local timeout    (router)                → purple
  LO = local IQR outlier (router)               → pink
  GT = gateway timeout  (ISP gateway)           → red
  GO = gateway IQR outlier (ISP gateway)        → orange

Priority: S > LT > LO > GT > GO  (logged per round; LO also logs gateway events)
Usage: python3 monitor.py [-t INTERVAL] [-l LOGFILE]
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

FLUSH_INTERVAL    = 60   # seconds
SUSPEND_THRESHOLD = 3    # multiples of interval
IQR_MIN_SAMPLES   = 30

# ANSI colors
RED    = "\033[31m"
PURPLE = "\033[35m"
PINK   = "\033[95m"
ORANGE = "\033[33m"
RESET  = "\033[0m"

EVENT_COLOR = {
    "S":  RED,
    "LT": PURPLE,
    "LO": PINK,
    "GT": RED,
    "GO": ORANGE,
}
PRIORITY = {"LT": 5, "LO": 4, "GT": 3, "GO": 2}


def get_local_subnet() -> tuple[int, int] | None:
    """Return (network_addr, netmask) as ints for the default route interface."""
    import ipaddress
    try:
        if sys.platform == "darwin":
            # Get default interface
            out = subprocess.check_output(["route", "-n", "get", "default"],
                                          text=True, timeout=3)
            iface_m = re.search(r"interface:\s+(\S+)", out)
            if not iface_m:
                return None
            iface = iface_m.group(1)
            # Get IP and netmask from ifconfig
            out = subprocess.check_output(["ifconfig", iface], text=True, timeout=3)
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+) netmask (0x[0-9a-fA-F]+)", out)
            if not m:
                return None
            ip_addr = int(ipaddress.IPv4Address(m.group(1)))
            netmask = int(m.group(2), 16)
            return (ip_addr & netmask, netmask)
        elif sys.platform.startswith("linux"):
            out = subprocess.check_output(["ip", "route", "show", "default"],
                                          text=True, timeout=3)
            dev_m = re.search(r"dev (\S+)", out)
            if not dev_m:
                return None
            dev = dev_m.group(1)
            out = subprocess.check_output(["ip", "-4", "addr", "show", dev],
                                          text=True, timeout=3)
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", out)
            if not m:
                return None
            net = ipaddress.IPv4Network(f"{m.group(1)}/{m.group(2)}", strict=False)
            return (int(net.network_address), int(net.netmask))
        return None
    except Exception:
        return None


def detect_targets() -> tuple[str | None, str | None]:
    """Detect local router and ISP gateway via traceroute + subnet info.

    Returns (local_ip, gateway_ip). Local = last hop in local subnet,
    gateway = first hop outside local subnet.
    """
    subnet = get_local_subnet()

    def is_local(ip_str: str) -> bool:
        if subnet is None:
            return False
        import ipaddress
        ip_int = int(ipaddress.IPv4Address(ip_str))
        net_addr, netmask = subnet
        return (ip_int & netmask) == net_addr

    try:
        cmd = ["traceroute", "-n", "-m", "5", "-q", "1", "-w", "2", "8.8.8.8"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        local_ip = None
        gateway_ip = None

        for line in result.stdout.splitlines():
            m = re.match(r"\s*\d+\s+([\d.]+)\s", line)
            if not m:
                continue
            hop = m.group(1)
            if subnet and is_local(hop):
                local_ip = hop  # keep updating — last local hop wins
            elif gateway_ip is None:
                if local_ip is None and subnet:
                    # First hop is already outside local net — unlikely but handle it
                    pass
                gateway_ip = hop
                if local_ip is not None:
                    break  # got both

        # Fallback: if no subnet info, hop 1 = local, hop 2 = gateway
        if subnet is None:
            hops = []
            for line in result.stdout.splitlines():
                m = re.match(r"\s*\d+\s+([\d.]+)\s", line)
                if m:
                    hops.append(m.group(1))
            local_ip = hops[0] if len(hops) >= 1 else None
            gateway_ip = hops[1] if len(hops) >= 2 else None

        return local_ip, gateway_ip
    except Exception:
        return None, None


def ping_host(host: str, timeout_s: int = 1) -> tuple[bool, float | None]:
    try:
        if sys.platform == "darwin":           # macOS: -W in milliseconds
            cmd = ["ping", "-c", "1", "-W", str(timeout_s * 1000), host]
        elif sys.platform.startswith("linux"): # Linux: -W in seconds
            cmd = ["ping", "-c", "1", "-W", str(timeout_s), host]
        else:                                  # Windows: -n count, -w in milliseconds
            cmd = ["ping", "-n", "1", "-w", str(timeout_s * 1000), host]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 1)
        if result.returncode == 0:
            m = re.search(r"time[=<]([\d.]+)\s*ms", result.stdout)
            return True, float(m.group(1)) if m else None
        return False, None
    except Exception:
        return False, None


def freq_stats(freq: dict[int, int]) -> tuple[float, float, float, float, float]:
    """Returns (mean, median, stddev, q1, q3)."""
    total = sum(freq.values())
    if total == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    mean = sum(k * v for k, v in freq.items()) / total
    variance = sum(v * (k - mean) ** 2 for k, v in freq.items()) / total
    stddev = math.sqrt(variance)
    sorted_keys = sorted(freq.keys())

    def pct(p: float) -> float:
        target, cum = p * total, 0
        for k in sorted_keys:
            cum += freq[k]
            if cum >= target:
                return float(k)
        return float(sorted_keys[-1])

    return mean, pct(0.5), stddev, pct(0.25), pct(0.75)


def is_iqr_outlier(val: float, q1: float, q3: float, n: int) -> bool:
    if n < IQR_MIN_SAMPLES:
        return False
    iqr = q3 - q1
    return iqr > 0 and val > q3 + 1.5 * iqr


def fmt_stats(avg: float, med: float, sd: float, n: int) -> str:
    if n == 0:
        return ""
    return f"(a={avg:5.1f} m={med:5.1f} s={sd:5.1f})"


def print_status(now: datetime, ping_count: int,
                 local_ms: float | None, l_avg: float, l_med: float, l_sd: float, l_n: int,
                 gw_ms: float | None,    g_avg: float, g_med: float, g_sd: float, g_n: int):
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    l = f"{local_ms:6.1f}ms" if local_ms is not None else " TIMEOUT"
    g = f"{gw_ms:6.1f}ms"    if gw_ms    is not None else " TIMEOUT"
    l_stats = fmt_stats(l_avg, l_med, l_sd, l_n)
    g_stats = fmt_stats(g_avg, g_med, g_sd, g_n)
    sys.stdout.write(
        f"\r{ts}  ping #{ping_count:>6}"
        f"  local={l}  {l_stats}"
        f"  gateway={g}  {g_stats}   "
    )
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Ping monitor — tracks local router & ISP gateway health")
    parser.add_argument("-t", "--interval", type=float, default=1.0,
                        help="Ping interval in seconds (default: 1)")
    parser.add_argument("--local", type=str, default=None,
                        help="Local router IP (default: auto-detected via traceroute)")
    parser.add_argument("--gateway", type=str, default=None,
                        help="ISP gateway IP (default: auto-detected via traceroute)")
    default_log = f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    parser.add_argument("-l", "--log", type=str, default=default_log,
                        help="Log file (default: log_<timestamp>.txt)")
    args = parser.parse_args()

    interval   = args.interval
    log_path   = args.log

    if args.local and args.gateway:
        local = args.local
        gateway = args.gateway
    else:
        print("Detecting targets via traceroute...")
        detected_local, detected_gateway = detect_targets()
        local = args.local or detected_local
        gateway = args.gateway or detected_gateway
        if local:
            print(f"  local:   {local}")
        if gateway:
            print(f"  gateway: {gateway}")

    if not local:
        local = "192.168.0.1"
        print(f"Could not detect local router, falling back to {local}")
    if not gateway:
        gateway = "8.8.8.8"
        print(f"Could not detect ISP gateway, falling back to {gateway}")

    last_flush = time.time()

    local_ping_freq:   dict[int, int] = {}
    gateway_ping_freq: dict[int, int] = {}

    event_desc = {
        "S":  "system suspended",
        "LT": f"local timeout         ({local})",
        "LO": f"local IQR outlier     ({local})",
        "GT": f"gateway timeout       ({gateway})",
        "GO": f"gateway IQR outlier   ({gateway})",
    }

    print(f"Ping monitor  |  interval={interval}s  |  log={log_path}")
    for k in ("S", "LT", "LO", "GT", "GO"):
        print(f"  {k:2} = {event_desc[k]}")
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
        color = EVENT_COLOR[event]
        desc  = event_desc[event]
        sys.stdout.write(f"\r{color}{ts_str}  event #{event_counter:>5}  {event:2}  — {desc}{extra}{RESET}\n")
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
                log_event(ts_str, "S")
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
                threading.Thread(target=_ping, args=(local,   "local"),   daemon=True),
                threading.Thread(target=_ping, args=(gateway, "gateway"), daemon=True),
            ]
            for t in threads: t.start()
            for t in threads: t.join()

            local_ok, local_ms = results["local"]
            gw_ok,    gw_ms    = results["gateway"]

            # Update frequency dicts
            if local_ok and local_ms is not None:
                k = round(local_ms)
                local_ping_freq[k] = local_ping_freq.get(k, 0) + 1
            if gw_ok and gw_ms is not None:
                k = round(gw_ms)
                gateway_ping_freq[k] = gateway_ping_freq.get(k, 0) + 1

            # Compute stats
            if local_ping_freq:
                l_avg, l_med, l_sd, l_q1, l_q3 = freq_stats(local_ping_freq)
                l_n = sum(local_ping_freq.values())
            else:
                l_avg = l_med = l_sd = l_q1 = l_q3 = 0.0
                l_n = 0

            if gateway_ping_freq:
                g_avg, g_med, g_sd, g_q1, g_q3 = freq_stats(gateway_ping_freq)
                g_n = sum(gateway_ping_freq.values())
            else:
                g_avg = g_med = g_sd = g_q1 = g_q3 = 0.0
                g_n = 0

            # Evaluate local and gateway events independently
            local_event = None
            if not local_ok:
                local_event = "LT"
            elif local_ms is not None and is_iqr_outlier(local_ms, l_q1, l_q3, l_n):
                local_event = "LO"

            gw_event = None
            if not gw_ok:
                gw_event = "GT"
            elif gw_ms is not None and is_iqr_outlier(gw_ms, g_q1, g_q3, g_n):
                gw_event = "GO"

            # Log: worst overall event; if LO, also log any gateway event separately
            candidates = [e for e in (local_event, gw_event) if e]
            if candidates:
                worst = max(candidates, key=lambda e: PRIORITY[e])
                extra_l = f"  ({local_ms:.1f}ms)" if local_event in ("LO",) else ""
                extra_g = f"  ({gw_ms:.1f}ms)"    if gw_event    in ("GO",) else ""

                if worst == local_event:
                    log_event(ts_str, local_event, extra_l)
                    if gw_event and local_event == "LO":
                        log_event(ts_str, gw_event, extra_g)
                else:
                    log_event(ts_str, gw_event, extra_g)

            print_status(now, ping_count,
                         local_ms, l_avg, l_med, l_sd, l_n,
                         gw_ms,    g_avg, g_med, g_sd, g_n)

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
