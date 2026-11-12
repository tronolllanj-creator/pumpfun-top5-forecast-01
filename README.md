# pumpfun-top5-forecast-01

This entry predicts the five highest-market-cap new pump.fun Solana coins at
the answer reads, plus a market-cap size distribution for each place.

`main.py` reads `task.json` and `history.ndjson` from `MAKEFUN_INPUT_DIR`
(default `/input`). It ranks coins from the final snapshot using log market
cap, 30-minute and one-hour log momentum, and a small graduation bonus. It
uses a place-shifted softmax with 0.65 named probability mass, leaves the
remainder for newcomers, and models each place's future log-cap as a widened
normal distribution. The output is written to
`MAKEFUN_OUTPUT_DIR/forecast.json` (default `/output`).

Run locally with:

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

The program uses only Python's standard library and produces byte-identical
output for identical input.
