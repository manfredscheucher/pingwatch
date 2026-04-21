# pingwatch

Tool to record ping timeouts and visualize network statistics.

## Requirements

```bash
pip install matplotlib numpy
```

## ping_monitor.py

Runs forever. Pings router and DNS every `t` seconds and logs events:

| Event | Meaning |
|-------|---------|
| A | Router timeout |
| B | DNS timeout |
| C | DNS ping > 100ms |

```bash
python3 ping_monitor.py [-t INTERVAL] [--router IP] [--dns IP] [-l LOGFILE]

# Examples
python3 ping_monitor.py
python3 ping_monitor.py -t 5 --router 10.0.0.1 --dns 1.1.1.1
```

## ping_histogram.py

Reads a log file and creates a grouped bar chart as PNG.

```bash
python3 ping_histogram.py LOG_FILE [--out OUTPUT.png]
```
