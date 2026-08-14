# AHDV-W1.2 Deribit DVOL Alignment Contract

Scope: derive production-vs-historical alignment for `deribit_dvol` after Wave 1 produced exact close mismatches.

## Production Semantics From Collector

`DeribitCollector` queries:

```text
public/get_volatility_index_data
currency=BTC
start_timestamp = now - 3h
end_timestamp = now
resolution = 3600
```

Production parser uses the last returned DVOL row:

```text
row = rows[-1]
raw_options_iv = row[4]
options_iv = row[4] / 100 if row[4] > 5 else row[4]
```

Deribit rows are treated as:

```text
[timestamp, open, high, low, close]
```

## Snapshot Comparison

| requested_as_of | historical candle | OHLC | snapshot raw | Exact close match | Range match |
| --- | --- | --- | ---: | --- | --- |
| `2026-07-04T09:05:55.641329+00:00` | `2026-07-04T09:00:00+00:00` | `38.97 / 39.06 / 38.95 / 39.03` | `None` | no snapshot raw | no |
| `2026-07-14T18:41:27.795808+00:00` | `2026-07-14T18:00:00+00:00` | `36.79 / 36.84 / 36.74 / 36.83` | `36.74` | no | yes |
| `2026-07-26T02:19:22.629347+00:00` | `2026-07-26T02:00:00+00:00` | `37.56 / 37.58 / 37.51 / 37.51` | `37.58` | no | yes |

## Interpretation

Exact `snapshot == historical close` is not a valid parity expectation when the snapshot was collected inside the 1h candle. Two valid snapshots fall within the historical candle high-low range, which suggests alignment drift rather than schema incompatibility.

The first selected snapshot is not usable for DVOL parity because production snapshot has:

```text
options_iv = 0.0
raw_options_iv = None
options_iv_unit = None
deribit status = missing
```

## Proposed Contract

For 1h DVOL history, parity should be evaluated as:

```text
candle_start <= snapshot_collected_at < candle_start + 1h
AND snapshot_raw_options_iv in [low, high]
AND options_iv_unit == "decimal"
```

Exact close equality is only valid if production collection occurs after candle close and the collector intentionally stores the closed candle value.

## Decision

Keep `deribit_dvol` as `UNCLASSIFIED`.

Next action is to rerun only the two valid Deribit ground-truth timestamps with the interval/range contract. Do not widen tolerance beyond the real production semantics.

