# pingwatch

Monitors router and DNS reachability, logs anomalies, and visualizes them as a histogram.

## Requirements

```bash
pip install matplotlib numpy
```

---

## ping_monitor.py

Runs forever. Pings router and DNS in parallel every `t` seconds (default: 1s).
Logs events to a timestamped file and prints live stats to the terminal.

### Events

| Event | Meaning | Color |
|-------|---------|-------|
| S  | System suspended (laptop sleep detected) | red |
| RT | Router timeout | purple |
| RO | Router latency IQR outlier (statistically unusual) | pink |
| DT | DNS timeout | red |
| DO | DNS latency IQR outlier (statistically unusual) | orange |

- **S** is detected when the monotonic clock jumps by more than 3× the ping interval.
- **RO / DO** are only triggered after ≥ 30 successful pings (to avoid false positives at startup).
- Router and DNS are evaluated independently — both can produce events in the same round.
- If **RO** occurs, any simultaneous DNS event (DT/DO) is also logged as a separate line.

### Usage

```bash
python3 ping_monitor.py [-t INTERVAL] [--router IP] [--dns IP] [-l LOGFILE]

# Examples
python3 ping_monitor.py
python3 ping_monitor.py -t 5 --router 10.0.0.1 --dns 1.1.1.1 -l my_log.txt
```

### Output

Each ping prints a single updating status line:
```
2026-04-22 14:30:07  ping #     3  router=  16.5ms  (a= 12.7 m= 16.0 s=  5.4)  dns=  36.0ms  (a= 37.3 m= 37.0 s=  1.2)
```

Events interrupt the status line with a colored entry:
```
2026-04-22 14:30:08  event #    1  RT  — router timeout (192.168.0.1)
```

---

## ping_histogram.py

Reads a log file and renders a grouped bar chart (PNG) of events by hour.

### Usage

```bash
python3 ping_histogram.py LOG_FILE [--out OUTPUT.png] [--router IP] [--dns IP] [--outliers]

# Examples
python3 ping_histogram.py log_20260422_143000.txt
python3 ping_histogram.py log_20260422_143000.txt --router 192.168.0.1 --dns 8.8.8.8
python3 ping_histogram.py log_20260422_143000.txt --outliers
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--out` / `-o` | `histogram.png` next to log | Output PNG path |
| `--router` | — | Router IP shown in chart title |
| `--dns` | — | DNS IP shown in chart title |
| `--outliers` | off | Also plot RO and DO outlier bars |
