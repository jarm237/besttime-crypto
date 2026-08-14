# AHDV-W1.3 Wave 1 Fallback Verification

Scope: read production collector paths and record fallback behavior for the six Wave 1 sources.

| Source | Disabled by env | HTTP/error fallback | Empty/schema fallback | Stale/last-known behavior | Runtime effect |
| --- | --- | --- | --- | --- | --- |
| `alternative_me` | `ENABLE_ALTERNATIVE_ME=false` returns `status=skipped`, `data=None` | On exception, returns cached payload as `status=stale` if in-memory cache exists; otherwise `status=unavailable` | Missing records/value raises and follows exception path | In-memory stale cache only | Aggregate payload records source status; missing fields remain `None`, stale data can still populate fields |
| `fred` | `ENABLE_FRED=false` returns `status=skipped`, `data=None` | If FRED key is `demo`, production uses Yahoo `^TNX` fallback; if FRED request fails, also tries Yahoo | Empty FRED observations try Yahoo fallback | No local stale cache | On total failure, returns `status=error`, `us10y=0.0`, `gold=0.0`; aggregate normalizer may treat zero as value unless downstream metadata rejects it |
| `binance_funding` | `ENABLE_BINANCE=false` returns `status=skipped`, `data=None` | Any exception makes whole Binance payload `status=error` with funding/OI/orderbook `None` | Missing funding leaves `funding_rate=None`; OI/depth get field statuses | No stale cache | Aggregate payload preserves `None`; `funding_pressure` remains `None` |
| `defillama_stablecoin` | `ENABLE_DEFILLAMA=false` returns `status=skipped`, `data=None` | Exceptions return `status=error`, stablecoin/TVL fields `None` with field error statuses | Stablecoin endpoint falls back to stablecoin chart endpoint; invalid/missing values get field statuses | No stale cache | Aggregate payload preserves `None`; momentum/effective momentum falls back to `0.0` only as effective weighted score |
| `defillama_tvl` | `ENABLE_DEFILLAMA=false` returns `status=skipped`, `data=None` | Exceptions return `status=error`, TVL fields `None` with field error statuses | Chain/protocol missing produces invalid field statuses; `tvl` is max of valid chain/protocol TVL | No stale cache | Aggregate payload preserves `None`; `defi_liquidity_score` currently remains `None` |
| `deribit_dvol` | `ENABLE_DERIBIT=false` returns `status=skipped`, `data=None` | Exceptions set `status=error`, `options_iv=None`, `iv_skew=None`, field errors | If DVOL parse fails, production falls back to option book summary median IV | No stale cache | Aggregate missing contract rejects non-positive options IV; valid IV populates `options_iv` and metadata |

## Replay Implication

Fallback is now known for all six Wave 1 sources at the collector boundary, but not all downstream effects are fully verified in replay. Historical replay should reproduce these collector statuses rather than invent proxy values.

## Stop Rule

If PIT fails but the fallback above is applicable, classify the source and proceed with production fallback. Do not add proxy/counterfactual data inside AHDV.

