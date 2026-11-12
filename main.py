#!/usr/bin/env python3
"""Deterministic pump.fun top-five forecast.

The hello entry reads one batch of snapshot orders; each row carries its slot.
It scores current coins with cap, recent momentum, and graduation, then emits
place probabilities and market-cap size probabilities for the forecast window.
Only the Python standard library is used, and no clock or network is touched.
"""

import json
import math
import os
from datetime import datetime, timedelta


INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
NAMED_MASS = 0.65
TOP_CANDIDATES = 12
TEMPERATURE = 0.22
PLACE_PENALTY = 0.35
MICRO = 1_000_000


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def clamp(value, low, high):
    return max(low, min(high, value))


def log_size(lamports):
    return math.log10(int(lamports)) - 9.0


def normal_tail(x, mean, sd):
    if x == -math.inf:
        return 1.0
    if x == math.inf:
        return 0.0
    return 0.5 * math.erfc((x - mean) / (sd * math.sqrt(2.0)))


def read_marks(path):
    marks = []
    with open(path, encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            mark = json.loads(line)
            if mark.get("ok") is True and isinstance(mark.get("rows"), list):
                marks.append(mark)
    marks.sort(key=lambda mark: mark["at"])
    return marks


def main():
    with open(os.path.join(INPUT_DIR, "task.json"), encoding="utf-8") as source:
        task = json.load(source)
    marks = read_marks(os.path.join(INPUT_DIR, "history.ndjson"))
    if not marks:
        raise SystemExit("history has no successful marks")

    places = int(task["places"])
    edges = [float(edge) for edge in task["size"]["edges"]]
    output_name = task.get("output", "forecast.json")
    last = marks[-1]
    last_at = timestamp(last["at"])
    last_rows = sorted(last["rows"], key=lambda row: (int(row["rank"]), row["mint"]))

    reads = task.get("reads", [])
    horizon = 0.0
    if reads:
        horizon = max(0.0, (timestamp(reads[0]) - last_at).total_seconds() / 3600.0)
    size_sd = min(0.65, 0.35 + 0.03 * horizon)

    # Keep the latest observed positive cap at each historical timestamp.
    series = {}
    for mark in marks:
        when = timestamp(mark["at"])
        for row in mark["rows"]:
            try:
                cap = int(row["market_cap_lamports"])
            except (KeyError, TypeError, ValueError):
                continue
            if cap > 0 and row.get("mint"):
                series.setdefault(row["mint"], []).append((when, cap))
    for observations in series.values():
        observations.sort(key=lambda item: item[0])

    def cap_before(observations, cutoff):
        found = None
        for when, cap in observations:
            if when > cutoff:
                break
            found = cap
        return found

    scored = []
    for row in last_rows:
        mint = row.get("mint")
        observations = series.get(mint, [])
        try:
            current = int(row["market_cap_lamports"])
        except (KeyError, TypeError, ValueError):
            continue
        if not mint or current <= 0 or not observations:
            continue
        current_log = log_size(current)
        old_30 = cap_before(observations, last_at - timedelta(minutes=30))
        old_60 = cap_before(observations, last_at - timedelta(minutes=60))
        growth_30 = math.log10(current / old_30) if old_30 else 0.0
        growth_60 = math.log10(current / old_60) if old_60 else 0.0
        momentum = 0.5 * clamp(growth_30, -1.0, 1.0) + 0.5 * clamp(growth_60, -1.0, 1.0)
        graduated = 1.0 if row.get("venue") == "pool" and row.get("complete") else 0.0
        score = current_log + 0.7 * momentum + 0.12 * graduated
        scored.append({
            "mint": mint,
            "score": score,
            "predicted": current_log + 0.5 * clamp(growth_60, -1.0, 1.0),
        })

    # A valid mark is unique by mint; retain the first (lowest-rank) duplicate
    # defensively so the promised top5 is distinct even on imperfect input.
    unique = {}
    for coin in scored:
        unique.setdefault(coin["mint"], coin)
    scored = list(unique.values())
    if len(scored) < places:
        raise SystemExit("last mark has fewer usable coins than places")
    scored.sort(key=lambda coin: (-coin["score"], coin["mint"]))
    for rank, coin in enumerate(scored, 1):
        coin["rank"] = rank

    candidates = scored[:TOP_CANDIDATES]
    probabilities = []
    for place in range(1, places + 1):
        adjusted = [coin["score"] - PLACE_PENALTY * abs(coin["rank"] - place) for coin in candidates]
        peak = max(adjusted)
        weights = [math.exp((value - peak) / TEMPERATURE) for value in adjusted]
        total = sum(weights)
        for coin, weight in zip(candidates, weights):
            probability = math.floor(NAMED_MASS * weight / total * MICRO) / MICRO
            if probability > 0.0:
                probabilities.append({"mint": coin["mint"], "place": place, "p": probability})

    sizes = []
    for place in range(1, places + 1):
        mean = scored[place - 1]["predicted"]
        for bin_number in range(len(edges) + 1):
            low = -math.inf if bin_number == 0 else edges[bin_number - 1]
            high = math.inf if bin_number == len(edges) else edges[bin_number]
            mass = normal_tail(low, mean, size_sd) - normal_tail(high, mean, size_sd)
            probability = math.floor(mass * MICRO) / MICRO
            if probability > 0.0:
                sizes.append({"place": place, "bin": bin_number, "p": probability})

    result = {
        "probabilities": probabilities,
        "top5": [coin["mint"] for coin in scored[:places]],
        "sizes": sizes,
    }
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, output_name), "w", encoding="utf-8") as target:
        target.write(json.dumps(result, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
