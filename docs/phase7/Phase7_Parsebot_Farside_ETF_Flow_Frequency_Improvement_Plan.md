# Phase 7 — Parse.bot Farside ETF Flow Frequency Improvement Plan

> **Runtime update (2026-07-29):** Với 5 API key và per-key guard 180,
> lịch `recent` đang dùng là `0 9,11,13,15,17,19 * * 2-6` theo múi giờ
> `Asia/Ho_Chi_Minh`. Scheduler hiện đọc trực tiếp các biến
> `PARSEBOT_*_CRON`. Lịch này có tối đa 429 request gốc hoặc 858 attempts khi
> mọi request retry một lần, dưới tổng guard 900. Các cron cũ phía dưới được
> giữ lại như lịch sử thiết kế và không còn là cấu hình runtime chuẩn.

## 1. Mục tiêu

Hiện tại hệ thống Phase 7 Alternative Data có thể gặp các lỗi dạng:

```text
parsebot_farside: Failed to fetch
All ETF providers failed; using default
```

Mục tiêu của bản cải tiến này:

1. Không gọi Parse.bot quá dày.
2. Không gọi ETF flow cho coin không được hỗ trợ.
3. Tách `recent`, `all`, và `fund_info` thành các job riêng.
4. Trading scan 15 phút chỉ đọc cache/local DB, không gọi Parse.bot trực tiếp.
5. Khi API fail thì trả trạng thái `failed`, `missing`, `stale`, hoặc `unsupported`, không dùng dữ liệu default giả.
6. Chuẩn hóa `.env` để dễ bật/tắt từng endpoint.

> **✅ IMPLEMENTATION COMPLETE (2026-07-07):** Tất cả các mục tiêu trên đã được triển khai đầy đủ. Xem Checklist §16 và `implementation_plan_comparison.md` để biết trạng thái từng hạng mục.

Các endpoint Parse.bot Farside ETF Flows cần hỗ trợ:

```text
get_bitcoin_etf_flows_recent
get_bitcoin_etf_flows_all
get_ethereum_etf_flows_recent
get_ethereum_etf_flows_all
get_solana_etf_flows
get_fund_info
```

---

## 2. Nguyên tắc tần suất gọi

ETF flow là dữ liệu theo ngày giao dịch, không phải dữ liệu tick-level hoặc candle-level. Vì vậy không nên gọi Parse.bot trong mỗi vòng scan thị trường 15 phút.

Thiết kế đúng:

```text
Parse.bot scheduled jobs
        ↓
Fetch ETF flow / fund info
        ↓
Normalize + save DB/cache
        ↓
Trading scan mỗi 15 phút
        ↓
Load latest ETF flow từ cache/local DB
        ↓
Nếu usable thì dùng feature, nếu failed/stale thì bỏ weight
```

Không nên:

```text
Trading scan mỗi 15 phút
        ↓
Call Parse.bot directly
        ↓
Scoring phụ thuộc API realtime
```

---

## 3. Tần suất gọi đề xuất

Timezone hệ thống:

```env
APP_TIMEZONE=Asia/Ho_Chi_Minh
```

### 3.1 Recent ETF flow endpoints

Áp dụng cho:

```text
get_bitcoin_etf_flows_recent
get_ethereum_etf_flows_recent
get_solana_etf_flows
```

Lịch gọi khuyến nghị theo giờ Việt Nam:

```text
06:00 VN
07:00 VN
08:00 VN
09:00 VN
```

Cron:

```cron
0 6,7,8,9 * * 2-6
```

Ý nghĩa:

- Chạy từ thứ 2 đến thứ 6 theo giờ Việt Nam.
- Phù hợp với khung sau phiên Mỹ, khi dữ liệu ETF flow thường đã có hoặc đang được cập nhật.
- Không gọi liên tục cả ngày.

### 3.2 Historical all endpoints

Áp dụng cho:

```text
get_bitcoin_etf_flows_all
get_ethereum_etf_flows_all
```

Lịch gọi khuyến nghị:

```text
09:30 VN, thứ 2 đến thứ 6
```

Cron:

```cron
30 9 * * 2-6
```

Mục đích:

- Backfill dữ liệu lịch sử.
- Kiểm tra lại dữ liệu ngày mới nhất.
- Rebuild feature khi cần.

Không nên gọi `all` nhiều lần trong ngày vì response thường lớn hơn và ít cần thiết cho realtime scoring.

### 3.3 Fund info endpoint

Áp dụng cho:

```text
get_fund_info
```

Lịch gọi khuyến nghị mặc định:

```text
10:00 VN mỗi ngày
```

Cron daily:

```cron
0 10 * * *
```

Nếu muốn tiết kiệm quota hơn, có thể chuyển sang weekly:

```cron
0 10 * * 1
```

---

## 4. Thay đổi `.env`

### 4.1 Parse.bot base config

Thêm vào `.env`:

```env
# ==================================================
# Parse.bot Farside ETF Flows
# ==================================================

PARSEBOT_ENABLED=true
PARSEBOT_API_KEY=your_parsebot_api_key_here
PARSEBOT_BASE_URL=https://your-parsebot-endpoint-from-dashboard

PARSEBOT_TIMEOUT_SECONDS=20
PARSEBOT_MAX_RETRIES=2
PARSEBOT_RETRY_DELAY_SECONDS=5
PARSEBOT_CACHE_TTL_HOURS=20

ETF_FLOW_PROVIDER=parsebot_farside
ETF_FLOW_TIMEZONE=Asia/Ho_Chi_Minh
```

Lưu ý quan trọng:

```text
PARSEBOT_BASE_URL phải lấy từ dashboard/subscription của Parse.bot.
Không hardcode https://api.parsebot.com nếu endpoint này không tồn tại hoặc không được cung cấp.
```

### 4.2 Endpoint names

Thêm endpoint name vào `.env` để không hardcode trong code:

```env
# Bitcoin ETF Flows
PARSEBOT_ENDPOINT_BTC_RECENT=get_bitcoin_etf_flows_recent
PARSEBOT_ENDPOINT_BTC_ALL=get_bitcoin_etf_flows_all

# Ethereum ETF Flows
PARSEBOT_ENDPOINT_ETH_RECENT=get_ethereum_etf_flows_recent
PARSEBOT_ENDPOINT_ETH_ALL=get_ethereum_etf_flows_all

# Solana ETF Flows
PARSEBOT_ENDPOINT_SOL_FLOWS=get_solana_etf_flows

# Farside Fund Info
PARSEBOT_ENDPOINT_FUND_INFO=get_fund_info
```

### 4.3 Scheduling config

```env
# Recent data: BTC/ETH/SOL
PARSEBOT_ETF_RECENT_CRON=0 6,7,8,9 * * 2-6

# Historical all data: BTC/ETH
PARSEBOT_ETF_ALL_CRON=30 9 * * 2-6

# Fund info
PARSEBOT_FUND_INFO_CRON=0 10 * * *
```

### 4.4 Supported symbols

```env
SUPPORTED_ETF_FLOW_SYMBOLS=BTC,ETH,SOL
SUPPORTED_ETF_RECENT_SYMBOLS=BTC,ETH,SOL
SUPPORTED_ETF_ALL_SYMBOLS=BTC,ETH
```

Ý nghĩa:

- `BTC`: support recent + all.
- `ETH`: support recent + all.
- `SOL`: support flow endpoint riêng `get_solana_etf_flows`.
- Các coin khác như `BNB`, `XRP`, `ADA`, `DOGE` không nên gọi ETF flow nếu provider không có endpoint thật.

### 4.5 Feature flags

```env
ENABLE_PARSEBOT_BTC_RECENT=true
ENABLE_PARSEBOT_BTC_ALL=true
ENABLE_PARSEBOT_ETH_RECENT=true
ENABLE_PARSEBOT_ETH_ALL=true
ENABLE_PARSEBOT_SOL_FLOWS=true
ENABLE_PARSEBOT_FUND_INFO=true
```

### 4.6 Fallback / cache / data quality

```env
ETF_FLOW_USE_CACHE_ON_FAIL=true
ETF_FLOW_MAX_STALE_HOURS=36
ETF_FLOW_DISABLE_WEIGHT_ON_FAIL=true
ETF_FLOW_DISABLE_WEIGHT_ON_STALE=true
ETF_FLOW_ALLOW_DEFAULT_FAKE_DATA=false
```

Cấu hình quan trọng nhất:

```env
ETF_FLOW_ALLOW_DEFAULT_FAKE_DATA=false
```

Không để collector fail rồi sinh dữ liệu neutral giả. Trong trading model, thiếu dữ liệu phải được biểu diễn là `missing`, `failed`, hoặc `stale`, không phải `0` hoặc `neutral` như dữ liệu thật.

---

## 5. `.env.example` hoàn chỉnh

```env
# ==================================================
# Parse.bot Farside ETF Flows
# ==================================================

PARSEBOT_ENABLED=true
PARSEBOT_API_KEY=
PARSEBOT_BASE_URL=

PARSEBOT_TIMEOUT_SECONDS=20
PARSEBOT_MAX_RETRIES=2
PARSEBOT_RETRY_DELAY_SECONDS=5
PARSEBOT_CACHE_TTL_HOURS=20

ETF_FLOW_PROVIDER=parsebot_farside
ETF_FLOW_TIMEZONE=Asia/Ho_Chi_Minh

# ==================================================
# Parse.bot Endpoint Names
# ==================================================

PARSEBOT_ENDPOINT_BTC_RECENT=get_bitcoin_etf_flows_recent
PARSEBOT_ENDPOINT_BTC_ALL=get_bitcoin_etf_flows_all

PARSEBOT_ENDPOINT_ETH_RECENT=get_ethereum_etf_flows_recent
PARSEBOT_ENDPOINT_ETH_ALL=get_ethereum_etf_flows_all

PARSEBOT_ENDPOINT_SOL_FLOWS=get_solana_etf_flows

PARSEBOT_ENDPOINT_FUND_INFO=get_fund_info

# ==================================================
# Parse.bot Scheduling
# ==================================================

PARSEBOT_ETF_RECENT_CRON=0 6,7,8,9 * * 2-6
PARSEBOT_ETF_ALL_CRON=30 9 * * 2-6
PARSEBOT_FUND_INFO_CRON=0 10 * * *

# ==================================================
# Supported ETF Symbols
# ==================================================

SUPPORTED_ETF_FLOW_SYMBOLS=BTC,ETH,SOL
SUPPORTED_ETF_RECENT_SYMBOLS=BTC,ETH,SOL
SUPPORTED_ETF_ALL_SYMBOLS=BTC,ETH

# ==================================================
# Feature Flags
# ==================================================

ENABLE_PARSEBOT_BTC_RECENT=true
ENABLE_PARSEBOT_BTC_ALL=true
ENABLE_PARSEBOT_ETH_RECENT=true
ENABLE_PARSEBOT_ETH_ALL=true
ENABLE_PARSEBOT_SOL_FLOWS=true
ENABLE_PARSEBOT_FUND_INFO=true

# ==================================================
# Fallback / Cache / Data Quality
# ==================================================

ETF_FLOW_USE_CACHE_ON_FAIL=true
ETF_FLOW_MAX_STALE_HOURS=36
ETF_FLOW_DISABLE_WEIGHT_ON_FAIL=true
ETF_FLOW_DISABLE_WEIGHT_ON_STALE=true
ETF_FLOW_ALLOW_DEFAULT_FAKE_DATA=false
```

---

## 6. Endpoint mapping trong code

### 6.1 Python mapping

```python
import os

PARSEBOT_ENDPOINTS = {
    "BTC": {
        "recent": os.getenv("PARSEBOT_ENDPOINT_BTC_RECENT", "get_bitcoin_etf_flows_recent"),
        "all": os.getenv("PARSEBOT_ENDPOINT_BTC_ALL", "get_bitcoin_etf_flows_all"),
    },
    "ETH": {
        "recent": os.getenv("PARSEBOT_ENDPOINT_ETH_RECENT", "get_ethereum_etf_flows_recent"),
        "all": os.getenv("PARSEBOT_ENDPOINT_ETH_ALL", "get_ethereum_etf_flows_all"),
    },
    "SOL": {
        "recent": os.getenv("PARSEBOT_ENDPOINT_SOL_FLOWS", "get_solana_etf_flows"),
        "all": None,
    },
    "FUND": {
        "info": os.getenv("PARSEBOT_ENDPOINT_FUND_INFO", "get_fund_info"),
    },
}
```

### 6.2 Endpoint resolver

```python
def get_parsebot_endpoint(symbol: str, mode: str) -> str | None:
    symbol = symbol.upper()
    symbol_config = PARSEBOT_ENDPOINTS.get(symbol)

    if not symbol_config:
        return None

    return symbol_config.get(mode)
```

Ví dụ:

```python
get_parsebot_endpoint("BTC", "recent")
# get_bitcoin_etf_flows_recent

get_parsebot_endpoint("ETH", "all")
# get_ethereum_etf_flows_all

get_parsebot_endpoint("SOL", "recent")
# get_solana_etf_flows
```

---

## 7. Collector response chuẩn

### 7.1 Khi fetch thành công

```python
{
    "source": "parsebot_farside",
    "endpoint": "get_bitcoin_etf_flows_recent",
    "symbol": "BTC",
    "mode": "recent",
    "status": "ok",
    "value": data,
    "data_quality": 1.0,
    "fetched_at": "2026-07-06T00:00:00Z",
    "error": None,
}
```

### 7.2 Khi API fail

```python
{
    "source": "parsebot_farside",
    "endpoint": "get_bitcoin_etf_flows_recent",
    "symbol": "BTC",
    "mode": "recent",
    "status": "failed",
    "value": None,
    "data_quality": 0.0,
    "fetched_at": "2026-07-06T00:00:00Z",
    "error": "timeout or 401 or 500",
}
```

### 7.3 Khi symbol không support

```python
{
    "source": "parsebot_farside",
    "symbol": "XRP",
    "mode": "recent",
    "status": "unsupported",
    "value": None,
    "data_quality": 0.0,
    "error": "ETF flow is only supported for BTC, ETH, SOL",
}
```

---

## 8. ParsebotFarsideETFCollector mẫu

```python
import os
import time
import requests
from datetime import datetime, timezone


PARSEBOT_ENDPOINTS = {
    "BTC": {
        "recent": os.getenv("PARSEBOT_ENDPOINT_BTC_RECENT", "get_bitcoin_etf_flows_recent"),
        "all": os.getenv("PARSEBOT_ENDPOINT_BTC_ALL", "get_bitcoin_etf_flows_all"),
    },
    "ETH": {
        "recent": os.getenv("PARSEBOT_ENDPOINT_ETH_RECENT", "get_ethereum_etf_flows_recent"),
        "all": os.getenv("PARSEBOT_ENDPOINT_ETH_ALL", "get_ethereum_etf_flows_all"),
    },
    "SOL": {
        "recent": os.getenv("PARSEBOT_ENDPOINT_SOL_FLOWS", "get_solana_etf_flows"),
        "all": None,
    },
    "FUND": {
        "info": os.getenv("PARSEBOT_ENDPOINT_FUND_INFO", "get_fund_info"),
    },
}


def get_parsebot_endpoint(symbol: str, mode: str) -> str | None:
    symbol = symbol.upper()
    symbol_config = PARSEBOT_ENDPOINTS.get(symbol)

    if not symbol_config:
        return None

    return symbol_config.get(mode)


class ParsebotFarsideETFCollector:
    def __init__(self):
        self.enabled = os.getenv("PARSEBOT_ENABLED", "false").lower() == "true"
        self.base_url = os.getenv("PARSEBOT_BASE_URL")
        self.api_key = os.getenv("PARSEBOT_API_KEY")
        self.timeout = int(os.getenv("PARSEBOT_TIMEOUT_SECONDS", "20"))
        self.max_retries = int(os.getenv("PARSEBOT_MAX_RETRIES", "2"))
        self.retry_delay = int(os.getenv("PARSEBOT_RETRY_DELAY_SECONDS", "5"))

    def headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def build_url(self, endpoint: str) -> str:
        return f"{self.base_url.rstrip('/')}/{endpoint}"

    def fetch(self, symbol: str, mode: str):
        if not self.enabled:
            return self._result(symbol, mode, "disabled", None, 0.0, "Parse.bot disabled")

        if not self.base_url or not self.api_key:
            return self._result(symbol, mode, "disabled", None, 0.0, "Missing Parse.bot config")

        endpoint = get_parsebot_endpoint(symbol, mode)

        if not endpoint:
            return self._result(symbol, mode, "unsupported", None, 0.0, f"Unsupported {symbol}/{mode}")

        url = self.build_url(endpoint)
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    headers=self.headers(),
                    timeout=self.timeout,
                )
                response.raise_for_status()

                data = response.json()

                return self._result(
                    symbol=symbol,
                    mode=mode,
                    status="ok",
                    value=data,
                    data_quality=1.0,
                    error=None,
                    endpoint=endpoint,
                )

            except Exception as e:
                last_error = str(e)

                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        return self._result(
            symbol=symbol,
            mode=mode,
            status="failed",
            value=None,
            data_quality=0.0,
            error=last_error,
            endpoint=endpoint,
        )

    def _result(self, symbol, mode, status, value, data_quality, error, endpoint=None):
        return {
            "source": "parsebot_farside",
            "endpoint": endpoint,
            "symbol": symbol.upper(),
            "mode": mode,
            "status": status,
            "value": value,
            "data_quality": data_quality,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
        }
```

---

## 9. Jobs cần tạo

### 9.1 Job: `fetch_parsebot_etf_recent`

Cron:

```cron
0 6,7,8,9 * * 2-6
```

Symbols:

```text
BTC, ETH, SOL
```

Pseudo-code:

```python
def fetch_parsebot_etf_recent_job():
    symbols = os.getenv("SUPPORTED_ETF_RECENT_SYMBOLS", "BTC,ETH,SOL").split(",")
    collector = ParsebotFarsideETFCollector()

    for symbol in symbols:
        result = collector.fetch(symbol=symbol, mode="recent")
        save_etf_flow_result(result)

        if result["status"] == "ok":
            update_latest_etf_cache(symbol, result)
```

### 9.2 Job: `fetch_parsebot_etf_all`

Cron:

```cron
30 9 * * 2-6
```

Symbols:

```text
BTC, ETH
```

Pseudo-code:

```python
def fetch_parsebot_etf_all_job():
    symbols = os.getenv("SUPPORTED_ETF_ALL_SYMBOLS", "BTC,ETH").split(",")
    collector = ParsebotFarsideETFCollector()

    for symbol in symbols:
        result = collector.fetch(symbol=symbol, mode="all")
        save_etf_flow_result(result)

        if result["status"] == "ok":
            upsert_historical_etf_flows(symbol, result["value"])
```

### 9.3 Job: `fetch_parsebot_fund_info`

Cron:

```cron
0 10 * * *
```

Pseudo-code:

```python
def fetch_parsebot_fund_info_job():
    collector = ParsebotFarsideETFCollector()
    result = collector.fetch(symbol="FUND", mode="info")
    save_fund_info_result(result)
```

---

## 10. BullMQ/NestJS scheduling mẫu

Nếu scheduler nằm ở NestJS:

```ts
await queue.add(
  'fetch-parsebot-etf-recent',
  {},
  {
    repeat: {
      pattern: process.env.PARSEBOT_ETF_RECENT_CRON || '0 6,7,8,9 * * 2-6',
      tz: process.env.ETF_FLOW_TIMEZONE || 'Asia/Ho_Chi_Minh',
    },
    removeOnComplete: true,
    removeOnFail: 50,
  },
);

await queue.add(
  'fetch-parsebot-etf-all',
  {},
  {
    repeat: {
      pattern: process.env.PARSEBOT_ETF_ALL_CRON || '30 9 * * 2-6',
      tz: process.env.ETF_FLOW_TIMEZONE || 'Asia/Ho_Chi_Minh',
    },
    removeOnComplete: true,
    removeOnFail: 50,
  },
);

await queue.add(
  'fetch-parsebot-fund-info',
  {},
  {
    repeat: {
      pattern: process.env.PARSEBOT_FUND_INFO_CRON || '0 10 * * *',
      tz: process.env.ETF_FLOW_TIMEZONE || 'Asia/Ho_Chi_Minh',
    },
    removeOnComplete: true,
    removeOnFail: 50,
  },
);
```

---

## 11. DB schema đề xuất

### 11.1 Collection: `alternative_data_etf_flows`

```json
{
  "source": "parsebot_farside",
  "symbol": "BTC",
  "mode": "recent",
  "endpoint": "get_bitcoin_etf_flows_recent",
  "status": "ok",
  "flow_date": "2026-07-03",
  "total_flow_usd_m": 123.4,
  "raw": {},
  "data_quality": 1.0,
  "fetched_at": "2026-07-06T00:00:00Z",
  "created_at": "2026-07-06T00:00:00Z",
  "updated_at": "2026-07-06T00:00:00Z"
}
```

MongoDB indexes:

```js
db.alternative_data_etf_flows.createIndex(
  { source: 1, symbol: 1, flow_date: -1 },
  { unique: true }
)

db.alternative_data_etf_flows.createIndex(
  { symbol: 1, status: 1, fetched_at: -1 }
)
```

### 11.2 Collection: `alternative_data_fetch_logs`

```json
{
  "source": "parsebot_farside",
  "endpoint": "get_ethereum_etf_flows_recent",
  "symbol": "ETH",
  "mode": "recent",
  "status": "failed",
  "error": "timeout",
  "fetched_at": "2026-07-06T00:00:00Z"
}
```

MongoDB index:

```js
db.alternative_data_fetch_logs.createIndex(
  { source: 1, endpoint: 1, fetched_at: -1 }
)
```

---

## 12. Trading scan sử dụng ETF flow

Trong vòng scan 15 phút, không gọi Parse.bot. Chỉ load latest record từ DB/cache.

```python
def get_etf_feature_for_scoring(symbol: str):
    latest = load_latest_etf_flow_from_cache(symbol)

    if not latest:
        return {
            "etf_flow_score": 0,
            "etf_flow_weight": 0,
            "etf_flow_status": "missing",
        }

    if latest["status"] != "ok":
        return {
            "etf_flow_score": 0,
            "etf_flow_weight": 0,
            "etf_flow_status": latest["status"],
        }

    if is_stale(latest, max_hours=int(os.getenv("ETF_FLOW_MAX_STALE_HOURS", "36"))):
        return {
            "etf_flow_score": 0,
            "etf_flow_weight": 0,
            "etf_flow_status": "stale",
        }

    return {
        "etf_flow_score": compute_etf_flow_score(latest),
        "etf_flow_weight": 1,
        "etf_flow_status": "ok",
    }
```

Không làm:

```python
if failed:
    etf_flow_score = 0.5
```

Vì model có thể hiểu sai rằng neutral là dữ liệu thật.

---

## 13. Scoring rule ban đầu

Gợi ý scoring đơn giản theo tổng flow USD million:

```python
def compute_etf_flow_score(total_flow_usd_m: float) -> float:
    if total_flow_usd_m >= 500:
        return 1.0
    if total_flow_usd_m >= 250:
        return 0.7
    if total_flow_usd_m >= 100:
        return 0.4
    if total_flow_usd_m > -100:
        return 0.0
    if total_flow_usd_m > -250:
        return -0.4
    if total_flow_usd_m > -500:
        return -0.7
    return -1.0
```

Các hướng improve sau:

```text
1-day flow
3-day cumulative flow
5-day cumulative flow
7-day inflow streak
Outflow streak
GBTC / ETHE outflow adjustment
Z-score theo lịch sử từng symbol
So sánh ETF flow với volume spot/futures
```

---

## 14. Dashboard nên hiển thị thêm

Dashboard Phase 7 nên có block ETF Flow Status:

```text
BTC: ok / stale / failed / unsupported
ETH: ok / stale / failed / unsupported
SOL: ok / stale / failed / unsupported
```

Các field nên hiển thị:

```text
symbol
status
endpoint
flow_date
total_flow_usd_m
data_quality
fetched_at
is_stale
error
```

Nếu failed:

```text
ETF flow skipped in scoring because data is unavailable.
```

Không hiển thị `0` như dữ liệu thật.

---

## 15. Monitoring và alert

Nên log theo endpoint:

```text
parsebot_farside.get_bitcoin_etf_flows_recent.ok
parsebot_farside.get_bitcoin_etf_flows_recent.failed
parsebot_farside.get_ethereum_etf_flows_recent.ok
parsebot_farside.get_solana_etf_flows.failed
```

Alert khi:

```text
ETF flow failed > 2 ngày liên tiếp
ETF flow stale > 36 giờ
Parse.bot trả 401/403
Parse.bot timeout liên tục
Response schema thay đổi
```

---

## 16. Checklist triển khai

### Phase A — Config

```text
[x] Thêm Parse.bot config vào .env
[x] Thêm endpoint name config
[x] Thêm cron config
[x] Thêm supported symbols config
[x] Thêm fallback/data quality config
[x] Cập nhật .env.example
```

### Phase B — Collector

```text
[x] Tạo ParsebotFarsideETFCollector
[x] Implement fetch(symbol, mode)
[x] Implement retry + timeout
[x] Implement endpoint resolver
[x] Implement unsupported symbol handling
[x] Không dùng default fake data
```

### Phase C — Storage

```text
[x] Tạo alternative_data_etf_flows (MongoDB, db.py)
[x] Tạo alternative_data_fetch_logs (MongoDB, db.py)
[x] Upsert theo source + symbol + flow_date
[x] Lưu raw response để debug
[x] Lưu data_quality/status
```

### Phase D — Scheduler

```text
[x] Job recent: 06:00, 07:00, 08:00, 09:00 VN (fetch_parsebot_etf_jobs.py)
[x] Job all: 09:30 VN
[x] Job fund_info: 10:00 VN
[x] Không gọi Parse.bot trong scan 15m
[x] Tích hợp tự động vào AlternativeDataScheduler._collect() theo timezone Asia/Ho_Chi_Minh
```

### Phase E — Scoring

```text
[x] Load ETF flow từ cache/DB
[x] Nếu status != ok thì weight = 0
[x] Nếu stale thì weight = 0
[x] Nếu unsupported thì weight = 0
[x] Nếu ok thì compute score
[x] Log rõ ETF feature được dùng hay bị skip
```

### Phase F — Monitoring

```text
[x] Log endpoint fail theo symbol/mode (alternative_data_fetch_logs)
[x] Alert nếu failed > 2 ngày liên tiếp (check_etf_alert_conditions)
[x] Dashboard hiển thị data_quality (print_dashboard ETF status block)
[x] Dashboard hiển thị last_fetched_at
[x] Dashboard hiển thị ETF flow stale/failed/unsupported
```

---

## 17. Kết luận cấu hình tần suất tối ưu

Cấu hình nên dùng:

```env
PARSEBOT_ETF_RECENT_CRON=0 6,7,8,9 * * 2-6
PARSEBOT_ETF_ALL_CRON=30 9 * * 2-6
PARSEBOT_FUND_INFO_CRON=0 10 * * *
```

Kiến trúc nên dùng:

```text
Scheduled Parse.bot Collector
        ↓
Normalize + Save DB/cache
        ↓
Trading scan 15m đọc cache
        ↓
Scoring dùng ETF weight nếu data ok
```

Kết quả mong muốn:

```text
1. Giảm call API.
2. Tránh tốn quota Parse.bot.
3. Không phụ thuộc API external trong realtime scan.
4. Không còn using default như dữ liệu thật.
5. Tách rõ ok / failed / stale / unsupported.
6. Chuẩn bị tốt hơn cho causal feature và meta model.
```
