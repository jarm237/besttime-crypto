# HMR-V4C-2A: Stablecoin Liquidity Provenance Audit Report

## Governance Rationale & Decision Verdict

- **Verdict**: `AUTHORIZED_V4C_2B`
- **Provenance Status**: `AUTHORIZED_V4C_2B`

### Class-Specific Provenance Verdicts

| Source Class | Verdict | Authorized for V4C-2B? |
| :--- | :--- | :---: |
| `S1_total_circulating_supply` | `PASS` | **Yes** |
| `S2_net_issuance_redemption` | `PASS` | **Yes** |
| `S3_exchange_stablecoin_balances` | `REJECT_ATTRIBUTION_LOOKAHEAD` | **No** |
| `S4_exchange_stablecoin_netflows` | `REJECT_ATTRIBUTION_LOOKAHEAD` | **No** |
| `S5_stablecoin_dominance` | `PASS` | **Yes** |

## Attribution-Lookahead Risk Analysis (S9)

Exchange balances (`S3`) and netflows (`S4`) rely heavily on **address attribution databases** (such as labeling which cold/hot wallets belong to Binance, Coinbase, etc.). Address attributions are frequently updated retrospectively:

> **Example**: A wallet entity active in 2023 is only identified by the provider as a Binance wallet in 2026. If the provider retroactively updates the 2023 historical balance to include this wallet, it introduces **Attribution Lookahead**, enabling the system to see transaction alignments that were not known at timestamp $t$.

Due to this structural risk and the lack of historical label vintage registries in the free public domain, classes `S3` and `S4` fail the `S9 (Attribution-vintage validity)` gate and are rejected with **`REJECT_ATTRIBUTION_LOOKAHEAD`**.

## PIT and Reconstruction Semantics (S6 - S7)

Total Circulating Supply (`S1`) and Net Issuance (`S2`) represent aggregate values derived directly from public smart contracts across multiple blockchains. Under `sampling_semantics`, these aggregate supply numbers are locked historical daily snapshots and are revision-free. Timezone sessions align to UTC, and we set `available_at` with a conservative 1-day release lag (`available_at = date + 1 day at 00:00 UTC`) to ensure full block propagation and data indexing parity.

## Historical Coverage & Probe Analysis

The DefiLlama historical charts API was probed successfully:
- **Status Code**: `200`
- **2023-2024 Daily Records Count**: `732` (100% daily coverage)

## Conclusion & Next Steps

Since `S1`, `S2`, and `S5` successfully passed all gates, stage `V4C-2` is authorized to proceed to the feature audit phase:
**`AUTHORIZED_V4C_2B`**

The feature audit scope for `V4C-2B` is restricted strictly to total supply and net issuance features. Exchange-balance features remain strictly blocked.
