#!/usr/bin/env python3
"""Research-only Alternative Historical Data Validation (AHDV) harness.

The harness intentionally defaults to no network access. Its first job is to
freeze an inventory from production collector contracts and create auditable
artifacts for later point-in-time probes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.collectors.feature_source_registry import feature_source_registry


BOUNDARY_FLAGS = (
    "READ_ONLY",
    "NON_EVIDENCE",
    "NO_ACTIVE_CANARY_MUTATION",
    "NO_RUNTIME_CONTROL_ACTION",
    "NO_MODEL_RETRAIN",
    "NO_POLICY_CHANGE",
)

FIDELITY_LEVELS = (
    "UNCLASSIFIED",
    "H0_UNAVAILABLE",
    "H1_HISTORICAL",
    "H2_AS_OF_RECONSTRUCTABLE",
    "H3_POINT_IN_TIME_VERIFIED",
    "H4_PRODUCTION_PARITY",
)

SOURCE_AUTHENTICITY_CLASSES = (
    "MARKET_OBSERVED",
    "EXTERNALLY_PUBLISHED",
    "RECONSTRUCTED_FROM_EXTERNAL_SOURCE",
    "RECONSTRUCTED_FROM_ENDOGENOUS_PRICE",
    "SYNTHETIC",
)

INDEPENDENT_INFORMATION_ELIGIBLE_CLASSES = (
    "MARKET_OBSERVED",
    "EXTERNALLY_PUBLISHED",
    "RECONSTRUCTED_FROM_EXTERNAL_SOURCE",
)

PROBE_OFFSETS = (
    ("T1_7D", timedelta(days=7)),
    ("T2_30D", timedelta(days=30)),
    ("T3_90D", timedelta(days=90)),
    ("T4_180D", timedelta(days=180)),
    ("T5_365D", timedelta(days=365)),
)

EVENT_PROBE_TIMESTAMPS = (
    ("E1_POST_ETF_LAUNCH", "2024-01-12T16:00:00+00:00"),
    ("E2_HALVING_WINDOW", "2024-04-20T00:00:00+00:00"),
    ("E3_2024_Q4_BREAKOUT", "2024-11-06T16:00:00+00:00"),
)

KNOWN_FIDELITY_OVERRIDES: dict[str, dict[str, str]] = {
    "alternative_me": {
        "T1_7D": "AVAILABLE",
        "PIT": "NOT_PROVEN",
        "Parity": "PARTIAL",
        "Fallback": "VERIFIED",
        "Fidelity": "H1_HISTORICAL",
        "Replay decision": "PRODUCTION_FALLBACK",
    },
    "fred": {
        "T1_7D": "PROBE_BLOCKED_ENVIRONMENT",
        "PIT": "UNKNOWN",
        "Parity": "UNKNOWN",
        "Fallback": "VERIFIED",
        "Replay decision": "PRODUCTION_FALLBACK",
    },
    "binance_funding": {
        "T1_7D": "AVAILABLE",
        "PIT": "NOT_PROVEN",
        "Parity": "PARTIAL_2_OF_3",
        "Fallback": "VERIFIED",
        "Fidelity": "H1_HISTORICAL",
        "Replay decision": "PRODUCTION_FALLBACK",
    },
    "defillama_stablecoin": {
        "T1_7D": "AVAILABLE",
        "PIT": "NOT_PROVEN",
        "Parity": "FAIL_0_OF_6",
        "Fallback": "VERIFIED",
        "Fidelity": "H1_HISTORICAL",
        "Replay decision": "PRODUCTION_FALLBACK",
    },
    "defillama_tvl": {
        "T1_7D": "AVAILABLE",
        "PIT": "NOT_PROVEN",
        "Parity": "FAIL_0_OF_9",
        "Fallback": "VERIFIED",
        "Fidelity": "H1_HISTORICAL",
        "Replay decision": "PRODUCTION_FALLBACK",
    },
    "deribit_dvol": {
        "T1_7D": "AVAILABLE",
        "PIT": "RECONSTRUCTABLE_WITH_CLOSED_CANDLE_ONLY",
        "Parity": "ALIGNMENT_CONTRACT_DEFINED",
        "Fallback": "VERIFIED",
        "Fidelity": "H2_AS_OF_RECONSTRUCTABLE",
        "Replay decision": "USE_RECONSTRUCTED_CLOSED_OBSERVATION",
    },
}


@dataclass(frozen=True)
class SourceContract:
    source_id: str
    production_source: str
    feature_names: tuple[str, ...]
    collector: str
    provider: str
    endpoints: tuple[str, ...]
    raw_input: str
    raw_fields_consumed: tuple[str, ...]
    timestamp_field: str
    derived_features: tuple[str, ...]
    cadence: str
    historical_target: str
    timestamp_semantics: tuple[str, ...]
    cache_ttl: str
    fallback: str
    normalization: str
    production_parity_notes: str
    wave: int
    provenance_class: str = "EXTERNALLY_PUBLISHED"
    independent_information_eligible: bool = True
    allowed_research_use: tuple[str, ...] = ("independent_information_candidate",)
    source_authenticity_notes: str = "A-1 provenance gate must be verified before statistical audit."


SOURCE_CONTRACTS: tuple[SourceContract, ...] = (
    SourceContract(
        source_id="alternative_me",
        production_source="alternative_me",
        feature_names=("fear_greed_raw", "fear_greed_score"),
        collector="AlternativeMeCollector",
        provider="Alternative.me Fear & Greed",
        endpoints=("https://api.alternative.me/fng/?limit=1",),
        raw_input="Fear & Greed observation: value, value_classification, timestamp",
        raw_fields_consumed=("value", "value_classification", "timestamp"),
        timestamp_field="timestamp -> fear_greed_observed_at",
        derived_features=("fear_greed_score", "risk_on_score"),
        cadence="daily",
        historical_target="12m+",
        timestamp_semantics=("observed_at from provider timestamp", "collector timestamp"),
        cache_ttl="ALTERNATIVE_ME_CACHE_TTL_SECONDS default 21600s",
        fallback="stale in-memory cache on error; unavailable without cache; env skip",
        normalization="normalize_fear_greed(raw_value), then normalize_alternative_payload derives fear_greed_score",
        production_parity_notes="Historical payload must use production normalize_fear_greed and aggregate normalizer.",
        wave=1,
    ),
    SourceContract(
        source_id="fred",
        production_source="fred",
        feature_names=("us10y",),
        collector="FredCollector",
        provider="FRED DGS10 with Yahoo ^TNX fallback",
        endpoints=(
            "https://api.stlouisfed.org/fred/series/observations?series_id=DGS10",
            "https://query2.finance.yahoo.com/v8/finance/chart/^TNX?interval=1d&range=2d",
        ),
        raw_input="macro observations for us10y; gold field currently defaults/overridden by Yahoo collector",
        raw_fields_consumed=("observations[-1].value", "Yahoo regularMarketPrice/close fallback"),
        timestamp_field="FRED date / Yahoo chart timestamp; collector timestamp in wrapper",
        derived_features=("macro_risk_score", "macro_pressure", "risk_on_score"),
        cadence="daily",
        historical_target="12m+",
        timestamp_semantics=("observation date", "collector timestamp", "FRED realtime vintage when configured"),
        cache_ttl="none in collector",
        fallback="Yahoo Finance current chart fallback when FRED key is demo or FRED fails",
        normalization="normalize_alternative_payload consumes us10y for macro_risk_score",
        production_parity_notes="Do not treat final revised FRED observations as PIT without realtime_start/realtime_end audit.",
        wave=1,
    ),
    SourceContract(
        source_id="binance_funding",
        production_source="binance",
        feature_names=("funding_rate",),
        collector="BinanceCollector",
        provider="Binance USD-M Futures",
        endpoints=("https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1",),
        raw_input="BTCUSDT funding rate",
        raw_fields_consumed=("fundingRate", "fundingTime"),
        timestamp_field="fundingTime",
        derived_features=("funding_pressure", "risk_on_score"),
        cadence="8h",
        historical_target="12m",
        timestamp_semantics=("fundingTime", "collector timestamp"),
        cache_ttl="none in collector",
        fallback="field-level missing/invalid statuses; env skip",
        normalization="normalize_alternative_payload derives funding_pressure from funding_rate",
        production_parity_notes="Historical funding endpoint must preserve fundingTime and fundingRate semantics.",
        wave=1,
    ),
    SourceContract(
        source_id="binance_open_interest",
        production_source="binance",
        feature_names=("open_interest",),
        collector="BinanceCollector",
        provider="Binance USD-M Futures",
        endpoints=("https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT",),
        raw_input="current BTCUSDT open interest snapshot",
        raw_fields_consumed=("openInterest",),
        timestamp_field="collector timestamp",
        derived_features=("open_interest_pressure",),
        cadence="current snapshot",
        historical_target="determine",
        timestamp_semantics=("collector timestamp",),
        cache_ttl="none in collector",
        fallback="field-level invalid status for zero/missing OI; env skip",
        normalization="normalize_alternative_payload compares current and previous open_interest",
        production_parity_notes="Current endpoint schema differs from historical OI endpoints; parity must be proven separately.",
        wave=1,
    ),
    SourceContract(
        source_id="binance_orderbook",
        production_source="binance",
        feature_names=("orderbook_imbalance",),
        collector="BinanceCollector",
        provider="Binance USD-M Futures",
        endpoints=("https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=100",),
        raw_input="top 100 bid/ask depth snapshot",
        raw_fields_consumed=("bids[][1]", "asks[][1]"),
        timestamp_field="collector timestamp",
        derived_features=("orderbook_imbalance",),
        cadence="current snapshot",
        historical_target="determine",
        timestamp_semantics=("collector timestamp",),
        cache_ttl="none in collector",
        fallback="missing_or_empty_depth field status; env skip",
        normalization="production computes (bid volume - ask volume) / total volume before aggregate normalizer",
        production_parity_notes="Order book cannot be replayed exactly without archived depth snapshots.",
        wave=3,
    ),
    SourceContract(
        source_id="defillama_stablecoin",
        production_source="defillama",
        feature_names=("stablecoin_supply", "stablecoin_supply_total"),
        collector="DefiLlamaCollector",
        provider="DefiLlama",
        endpoints=("https://stablecoins.llama.fi/stablecoins", "https://stablecoins.llama.fi/stablecoincharts/all"),
        raw_input="stablecoin pegged USD totals",
        raw_fields_consumed=("total", "data.totalStablecoins", "peggedAssets[].circulating", "chart totalCirculating"),
        timestamp_field="chart row date when historical; collector timestamp otherwise",
        derived_features=("stablecoin_momentum", "effective_stablecoin_momentum"),
        cadence="daily",
        historical_target="12m",
        timestamp_semantics=("provider chart date when historical", "collector timestamp"),
        cache_ttl="none in collector",
        fallback="stablecoins endpoint then stablecoincharts",
        normalization="production parser extracts/sums pegged USD and aggregate normalizer derives momentum",
        production_parity_notes="Chart rows must not be summed across time; choose as-of row only.",
        wave=1,
    ),
    SourceContract(
        source_id="defillama_tvl",
        production_source="defillama",
        feature_names=("tvl", "chain_tvl"),
        collector="DefiLlamaCollector",
        provider="DefiLlama",
        endpoints=("https://api.llama.fi/v2/chains", "https://api.llama.fi/protocols"),
        raw_input="chain and protocol TVL",
        raw_fields_consumed=("chains[].tvl", "protocols[].tvl"),
        timestamp_field="collector timestamp for current endpoints",
        derived_features=("defi_liquidity_score",),
        cadence="daily/hourly depending endpoint",
        historical_target="12m",
        timestamp_semantics=("provider timestamp if historical endpoint exists", "collector timestamp"),
        cache_ttl="none in collector",
        fallback="chain/protocol TVL optional; invalid field status when missing",
        normalization="production sums numeric TVL fields and chooses max(chain_tvl, protocol_tvl)",
        production_parity_notes="Current aggregate endpoints may not provide PIT TVL; historical endpoint/schema parity must be proven.",
        wave=1,
    ),
    SourceContract(
        source_id="deribit_dvol",
        production_source="deribit",
        feature_names=("options_iv",),
        collector="DeribitCollector",
        provider="Deribit public API",
        endpoints=("https://www.deribit.com/api/v2/public/get_volatility_index_data",),
        raw_input="DVOL OHLC rows",
        raw_fields_consumed=("result.data[-1][0]", "result.data[-1][4]"),
        timestamp_field="DVOL row timestamp",
        derived_features=("options_iv",),
        cadence="hourly",
        historical_target="12m",
        timestamp_semantics=("DVOL row timestamp",),
        cache_ttl="none in collector",
        fallback="book summary median IV if DVOL missing",
        normalization="production parser normalizes IV percentages to decimals",
        production_parity_notes="Historical DVOL rows need PIT row timestamp and same close-field semantics.",
        wave=1,
        provenance_class="RECONSTRUCTED_FROM_EXTERNAL_SOURCE",
        independent_information_eligible=True,
        allowed_research_use=("independent_information_candidate", "volatility_state_control"),
        source_authenticity_notes=(
            "Deribit publishes DVOL rows; current evidence is H2/as-of reconstructable, "
            "not archived H3/H4 PIT parity."
        ),
    ),
    SourceContract(
        source_id="deribit_iv_skew",
        production_source="deribit",
        feature_names=("iv_skew",),
        collector="DeribitCollector",
        provider="Deribit public API",
        endpoints=("https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option",),
        raw_input="option book summaries with mark_iv/delta by instrument",
        raw_fields_consumed=("instrument_name", "mark_iv", "delta/greeks.delta", "underlying_price"),
        timestamp_field="collector timestamp",
        derived_features=("iv_skew",),
        cadence="minutes/current snapshot",
        historical_target="12m",
        timestamp_semantics=("option summary collector timestamp",),
        cache_ttl="none in collector",
        fallback="field-level missing status when insufficient 25d put/call samples",
        normalization="production computes matched-expiry put IV minus call IV near 25 delta",
        production_parity_notes="Book summary endpoint is current-state; historical option chain parity requires archive/provenance.",
        wave=1,
        provenance_class="MARKET_OBSERVED",
        independent_information_eligible=True,
        allowed_research_use=("independent_information_candidate",),
        source_authenticity_notes=(
            "Production current snapshot is market-observed. V4A-2-R historical series is a separate "
            "endogenous reconstructed proxy and is not eligible as genuine Deribit IV skew."
        ),
    ),
    SourceContract(
        source_id="etf",
        production_source="etf",
        feature_names=("etf_flow",),
        collector="ETFCollector",
        provider="ETFProviderChain / Parsebot Farside",
        endpoints=("provider-chain-defined", "parsebot_farside_cache"),
        raw_input="US spot BTC ETF net flow",
        raw_fields_consumed=("total_flow_usd_m", "etf_flow_status", "provider fields"),
        timestamp_field="flow date / provider cache timestamp",
        derived_features=("etf_momentum", "effective_etf_momentum"),
        cadence="daily",
        historical_target="determine",
        timestamp_semantics=("flow date", "provider cache timestamp", "collector timestamp"),
        cache_ttl="provider dependent",
        fallback="disabled by default; provider chain; optional fake defaults only if explicitly allowed",
        normalization="normalize_alternative_payload derives etf_momentum from previous payload",
        production_parity_notes="Disabled/default placeholder means replay should use production fallback unless provider archive is validated.",
        wave=2,
    ),
    SourceContract(
        source_id="google_trends",
        production_source="google_trends",
        feature_names=("sentiment_score",),
        collector="GoogleTrendsCollector",
        provider="pytrends unofficial Google Trends",
        endpoints=("pytrends interest_over_time timeframe=now 7-d",),
        raw_input="bitcoin search interest",
        raw_fields_consumed=("interest_over_time()[bitcoin].iloc[-1]",),
        timestamp_field="pytrends row time / cache cached_at",
        derived_features=("sentiment_score",),
        cadence="hourly/daily",
        historical_target="determine",
        timestamp_semantics=("pytrends row time", "cache cached_at", "collector timestamp"),
        cache_ttl="CACHE_FRESHNESS_SECONDS 21600s",
        fallback="disabled by default; cache; rate_limited/missing statuses",
        normalization="raw 0..100 score divided by 100 as sentiment_score",
        production_parity_notes="Trends values are rescaled by query window; historical recomputation must freeze query window semantics.",
        wave=2,
    ),
    SourceContract(
        source_id="reddit",
        production_source="reddit",
        feature_names=("social_sentiment",),
        collector="RedditCollector",
        provider="RedditOAuthCollector",
        endpoints=("Reddit OAuth API via configured collector",),
        raw_input="posts/comments sentiment, volume, z-score",
        raw_fields_consumed=("sentiment_score", "sentiment_volume", "sentiment_zscore", "posts_analyzed"),
        timestamp_field="post/comment created time and collector timestamp",
        derived_features=("social_sentiment",),
        cadence="realtime",
        historical_target="determine",
        timestamp_semantics=("post/comment created time", "collector timestamp"),
        cache_ttl="none in wrapper collector",
        fallback="disabled by default; minimum sample gate; missing status",
        normalization="collector emits sentiment_score/social_sentiment and sample counts",
        production_parity_notes="Historical scores must recompute derived metrics only with observations available_at <= replay T.",
        wave=3,
    ),
)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def probe_timestamps(anchor: datetime) -> list[dict[str, str]]:
    relative = [
        {"id": label, "as_of": (anchor - offset).isoformat()}
        for label, offset in PROBE_OFFSETS
    ]
    events = [{"id": label, "as_of": timestamp} for label, timestamp in EVENT_PROBE_TIMESTAMPS]
    return relative + events


def _feature_map_by_source() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for feature, spec in feature_source_registry().items():
        entry = {"feature": feature, **spec}
        grouped.setdefault(spec["source"], []).append(entry)
    return grouped


def build_source_inventory(anchor: datetime) -> list[dict[str, Any]]:
    features_by_source = _feature_map_by_source()
    inventory = []
    for contract in SOURCE_CONTRACTS:
        available_features = features_by_source.get(contract.production_source, [])
        features = [
            item for item in available_features
            if item["feature"] in set(contract.feature_names)
        ]
        features = sorted(features, key=lambda item: item["feature"])
        inventory.append(
            {
                **asdict(contract),
                "source_authenticity_gate": "A-1",
                "production_features": [item["feature"] for item in features],
                "feature_contracts": features,
                "validation_boundary": list(BOUNDARY_FLAGS),
                "inventory_generated_at": anchor.isoformat(),
                "inventory_source": "production collector code + feature_source_registry",
                "initial_fidelity": "UNCLASSIFIED",
                "initial_replay_decision": "PENDING_VALIDATION",
            }
        )
    return inventory


def _payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_probe_results(inventory: Iterable[dict[str, Any]], timestamps: Iterable[dict[str, str]], retrieved_at: datetime) -> list[dict[str, Any]]:
    results = []
    for source in inventory:
        for timestamp in timestamps:
            payload = {
                "source": source["source_id"],
                "requested_as_of": timestamp["as_of"],
                "probe_id": timestamp["id"],
                "network_policy": "disabled",
            }
            results.append(
                {
                    **payload,
                    "retrieved_at": retrieved_at.isoformat(),
                    "source_timestamp": None,
                    "raw_sha256": _payload_hash(payload),
                    "request_parameters": {"as_of": timestamp["as_of"], "network": "disabled"},
                    "availability_gate": "AMBIGUOUS",
                    "probe_status": "NOT_PROBED",
                    "temporal_correctness": {
                        "future_information_count": None,
                        "gate": "NOT_EVALUATED",
                        "cutoff_field": "available_at",
                    },
                    "payload": payload,
                }
            )
    return results


def build_fidelity_matrix(inventory: Iterable[dict[str, Any]], timestamps: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    columns = [item["id"] for item in timestamps]
    matrix = []
    for source in inventory:
        row = {
            "source": source["source_id"],
            **{column: "NOT_PROBED" for column in columns},
            "Earliest usable": "UNKNOWN",
            "PIT": "NOT_EVALUATED",
            "Parity": "NOT_EVALUATED",
            "Fallback": "NOT_VERIFIED",
            "Fidelity": "UNCLASSIFIED",
            "Replay decision": "PENDING_VALIDATION",
            "wave": source["wave"],
            "notes": source["production_parity_notes"],
        }
        row.update(KNOWN_FIDELITY_OVERRIDES.get(source["source_id"], {}))
        matrix.append(row)
    return matrix


def build_validation_manifest(anchor: datetime, timestamps: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "workstream": "Alternative Historical Data Validation",
        "short_name": "AHDV",
        "generated_at": anchor.isoformat(),
        "boundary": list(BOUNDARY_FLAGS),
        "fidelity_levels": list(FIDELITY_LEVELS),
        "probe_timestamps": timestamps,
        "gate_sequence": [
            {"gate": "G0", "name": "Production contract inventory"},
            {
                "gate": "A-1",
                "name": "Source authenticity",
                "classes": list(SOURCE_AUTHENTICITY_CLASSES),
                "eligible_for_independent_information": list(INDEPENDENT_INFORMATION_ELIGIBLE_CLASSES),
                "hard_rule": (
                    "RECONSTRUCTED_FROM_ENDOGENOUS_PRICE and SYNTHETIC are controls, "
                    "derived state, or pipeline validation only."
                ),
            },
            {"gate": "G1", "name": "Historical availability / retention"},
            {"gate": "G2", "name": "Temporal / PIT correctness", "hard_rule": "available_at <= replay_clock"},
            {"gate": "G3", "name": "Production normalization parity"},
            {"gate": "G4", "name": "Existing snapshot comparison"},
            {"gate": "G5", "name": "Determinism / repeat-query stability"},
            {"gate": "G6", "name": "Fidelity classification"},
            {"gate": "G7", "name": "Replay eligibility decision"},
        ],
        "promotion_rules": {
            "UNCLASSIFIED": "Initial state before probes; no source is assumed usable or unusable.",
            "H0_UNAVAILABLE": "Historical data unavailable.",
            "H1_HISTORICAL": "Historical records exist but knowledge-at-T correctness is not established.",
            "H2_AS_OF_RECONSTRUCTABLE": "Can reconstruct using only data <= T, without authoritative PIT snapshot/vintage proof.",
            "H3_POINT_IN_TIME_VERIFIED": "PIT correctness verified against vintage/archive/snapshot.",
            "H4_PRODUCTION_PARITY": "H3 plus production normalizer/feature semantics parity and deterministic replay behavior.",
        },
        "source_authenticity_rules": {
            "MARKET_OBSERVED": "Directly observed market venue/provider data.",
            "EXTERNALLY_PUBLISHED": "Published by an external provider, not derived from local target price state.",
            "RECONSTRUCTED_FROM_EXTERNAL_SOURCE": "Rebuilt from external observations with explicit availability semantics.",
            "RECONSTRUCTED_FROM_ENDOGENOUS_PRICE": "Derived from the same instrument price/volatility state under audit.",
            "SYNTHETIC": "Simulated or generated data.",
            "independent_information_candidates": list(INDEPENDENT_INFORMATION_ELIGIBLE_CLASSES),
            "control_only": ["RECONSTRUCTED_FROM_ENDOGENOUS_PRICE", "SYNTHETIC"],
        },
        "replay_decision_rules": {
            "H4_PRODUCTION_PARITY": "USE_EXACT",
            "H3_POINT_IN_TIME_VERIFIED": "USE_EXACT or USE_WITH_PARITY_NOTE",
            "H2_AS_OF_RECONSTRUCTABLE": "USE_RECONSTRUCTED only in sensitivity/research replay",
            "H1_HISTORICAL": "PRODUCTION_FALLBACK or EXCLUDE",
            "H0_UNAVAILABLE": "PRODUCTION_FALLBACK plus START_REALTIME_ARCHIVE",
        },
        "acceptance_criteria": {
            "TEMPORAL_ALIGNMENT": "future records = 0",
            "SCHEMA_PARITY": "PASS",
            "NORMALIZATION_PARITY": "PASS",
            "UNIT_PARITY": "PASS",
            "TIMEZONE_PARITY": "PASS",
            "DUPLICATES": 0,
            "INVALID_TIMESTAMP": 0,
            "RETENTION_BOUNDARY": "KNOWN",
            "EARLIEST_USABLE_TIMESTAMP": "KNOWN",
            "HISTORICAL_FIDELITY": "H0..H4",
            "PRODUCTION_FALLBACK": "VERIFIED",
            "RAW_PAYLOAD_ARCHIVED": "YES",
        },
        "stop_condition": (
            "For every source answer: availability known, retention boundary known, PIT correctness known, "
            "production parity known, fallback known, fidelity assigned, replay decision assigned."
        ),
        "default_network_policy": "disabled",
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_report(path: Path, matrix: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    headers = [
        "Source",
        "7d",
        "30d",
        "90d",
        "180d",
        "365d",
        "Earliest usable",
        "PIT",
        "Parity",
        "Fallback",
        "Fidelity",
        "Replay decision",
    ]
    lines = [
        "# Alternative Historical Data Validation",
        "",
        "This artifact is research-only and non-evidence until probes prove PIT correctness.",
        "",
        "Boundary: " + ", ".join(manifest["boundary"]),
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in matrix:
        lines.append(
            "| {source} | {T1_7D} | {T2_30D} | {T3_90D} | {T4_180D} | {T5_365D} | {Earliest usable} | {PIT} | {Parity} | {Fallback} | {Fidelity} | {Replay decision} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Next Gates",
            "",
            "0. Freeze production contract inventory: source, endpoint/provider, raw fields, timestamp field, normalizer, derived feature, cache/TTL, fallback.",
            "1. Classify A-1 source authenticity before any independent-information claim.",
            "2. Run historical availability and retention probes per timestamp and archive raw responses with hashes.",
            "3. Check `available_at <= replay_clock` for every record.",
            "4. Feed historical payloads through production normalization and compare schema/units/timezone.",
            "5. Compare against existing raw snapshots before promoting any source to H3/H4.",
            "6. Repeat queries to prove deterministic behavior before final replay eligibility.",
            "",
            "## Wave 1 Closeout",
            "",
            "Wave 1 is frozen. Do not continue provider investigation on the critical path. Move to Historical Market Replay V1 with two profiles:",
            "",
            "- `STRICT_V1`: PIT-safe data plus production fallback.",
            "- `RESEARCH_V1`: includes historical H1/H2 data with `NON_PIT_VERIFIED` where applicable.",
            "",
            "Replay must never use high/low/close from a candle containing `T` before that candle is complete.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_artifacts(output_dir: Path, anchor: datetime) -> dict[str, Path]:
    timestamps = probe_timestamps(anchor)
    inventory = build_source_inventory(anchor)
    manifest = build_validation_manifest(anchor, timestamps)
    probe_results = build_probe_results(inventory, timestamps, anchor)
    matrix = build_fidelity_matrix(inventory, timestamps)

    raw_dir = output_dir / "raw"
    normalized_dir = output_dir / "normalized"
    for source in inventory:
        (raw_dir / source["source_id"]).mkdir(parents=True, exist_ok=True)
        (normalized_dir / source["source_id"]).mkdir(parents=True, exist_ok=True)

    paths = {
        "source_inventory": output_dir / "source_inventory.json",
        "validation_manifest": output_dir / "validation_manifest.json",
        "probe_results": output_dir / "probe_results.jsonl",
        "coverage_report": output_dir / "coverage_report.json",
        "fidelity_matrix": output_dir / "fidelity_matrix.json",
        "final_report": output_dir / "final_report.md",
    }
    write_json(paths["source_inventory"], inventory)
    write_json(paths["validation_manifest"], manifest)
    write_jsonl(paths["probe_results"], probe_results)
    write_json(
        paths["coverage_report"],
        {
            "generated_at": anchor.isoformat(),
            "network_policy": "disabled",
            "sources": [
                {
                    "source": source["source_id"],
                    "earliest_usable_timestamp": "UNKNOWN",
                    "retention_boundary": "UNKNOWN",
                    "fallback_verified": "NOT_VERIFIED",
                    "missing_ratio": "UNKNOWN",
                    "expected_cadence": source["cadence"],
                    "maximum_gap": "UNKNOWN",
                    "continuity": "NOT_EVALUATED",
                }
                for source in inventory
            ],
        },
    )
    write_json(paths["fidelity_matrix"], matrix)
    write_report(paths["final_report"], matrix, manifest)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate AHDV research artifacts without mutating runtime state.")
    parser.add_argument(
        "--output-dir",
        default="research/alternative_history_validation",
        help="Artifact directory. Defaults to research/alternative_history_validation.",
    )
    parser.add_argument(
        "--anchor-time",
        default=datetime.now(timezone.utc).isoformat(),
        help="UTC anchor timestamp for T1..T5 probes. Defaults to now.",
    )
    args = parser.parse_args(argv)

    anchor = parse_utc(args.anchor_time)
    paths = generate_artifacts(Path(args.output_dir), anchor)
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
