# pingwatch

Monitors local router and ISP gateway reachability, logs anomalies, and visualizes them as histograms.

## Requirements

```bash
pip install matplotlib numpy
```

---

## monitor.py

Runs forever. Pings local router and ISP gateway in parallel every `t` seconds (default: 1s).
Both targets are auto-detected via a single `traceroute` at startup (local = last hop in local subnet, gateway = first hop outside).
Logs events to a timestamped file and prints live stats to the terminal.

### Events

| Event | Meaning | Color |
|-------|---------|-------|
| S  | System suspended (laptop sleep detected) | red |
| LT | Local timeout (router) | purple |
| LO | Local latency IQR outlier (statistically unusual) | pink |
| GT | Gateway timeout (ISP gateway) | red |
| GO | Gateway latency IQR outlier (statistically unusual) | orange |

- **S** is detected when the monotonic clock jumps by more than 3× the ping interval.
- **LO / GO** are only triggered after ≥ 30 successful pings (to avoid false positives at startup).
- Local and gateway are evaluated independently — both can produce events in the same round.
- If **LO** occurs, any simultaneous gateway event (GT/GO) is also logged as a separate line.

### Usage

```bash
python3 monitor.py [-t INTERVAL] [--local IP] [--gateway IP] [-l LOGFILE]

# Examples
python3 monitor.py
python3 monitor.py -t 5 --local 10.0.0.1 --gateway 172.20.167.133 -l my_log.txt
```

### Output

```
Detecting targets via traceroute...
  local:   192.168.0.1
  gateway: 172.20.167.133
```

Each ping prints a single updating status line:
```
2026-04-30 14:30:07  ping #     3  local=  16.5ms  (a= 12.7 m= 16.0 s=  5.4)  gateway=  36.0ms  (a= 37.3 m= 37.0 s=  1.2)
```

Events interrupt the status line with a colored entry:
```
2026-04-30 14:30:08  event #    1  LT  — local timeout (192.168.0.1)
```

---

## histogram.py

Reads a log file and renders a grouped bar chart (PNG) of events by hour.
Accepts both old (RT/RO/DT/DO) and new (LT/LO/GT/GO) log formats.

### Usage

```bash
python3 histogram.py LOG_FILE [--out OUTPUT.png] [--local IP] [--gateway IP] [--outliers] [--mode stacked|combined|split]

# Examples
python3 histogram.py log_20260430_093145.txt
python3 histogram.py log_20260430_093145.txt --local 192.168.0.1 --gateway 172.20.167.133
python3 histogram.py log_20260430_093145.txt --outliers
python3 histogram.py log_20260430_093145.txt --mode combined
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--out` / `-o` | `<logfile>.png` | Output PNG path |
| `--local` | — | Local router IP shown in chart title |
| `--gateway` | — | ISP gateway IP shown in chart title |
| `--outliers` | off | Also plot LO and GO outlier bars |
| `--mode` / `-m` | `stacked` | `stacked`: one subplot per day; `combined`: all in one row; `split`: one PNG per day |
