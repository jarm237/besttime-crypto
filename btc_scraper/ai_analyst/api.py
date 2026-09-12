import datetime
import random
import time
from google import genai
from btc_scraper.core.config import GEMINI_API_KEYS
from .utils import _parse_retry_delay

class _GeminiKeyManager:
    """
    Quản lý round-robin và trạng thái 429 cho danh sách Gemini API keys.
    - Mỗi lần gọi sử dụng key tiếp theo trong vòng xoay (round-robin).
    - Khi một key bị 429, bỏ qua ngay và dùng key kế tiếp.
    - Khi tất cả key đều bị 429, đánh dấu "paused" đến 00:05 hôm sau.
    """

    def __init__(self, keys: list[str]):
        self._keys = list(dict.fromkeys(keys))   # loại trùng lặp, giữ thứ tự
        self._index = 0                           # con trỏ round-robin
        self._exhausted: set[str] = set()         # keys đang bị 429
        self._paused_until: datetime.datetime | None = None

    # ------------------------------------------------------------------ #
    #  Properties                                                          #
    # ------------------------------------------------------------------ #

    @property
    def available(self) -> bool:
        """Trả về True nếu có ít nhất 1 key có thể dùng ngay bây giờ."""
        if not self._keys:
            return False
        if self._paused_until:
            if datetime.datetime.now() < self._paused_until:
                return False
            # Đã qua thời gian tạm dừng → reset
            self._paused_until = None
            self._exhausted.clear()
        return len(self._exhausted) < len(self._keys)

    @property
    def pause_info(self) -> str:
        """Thông báo thời điểm hết tạm dừng."""
        if self._paused_until:
            return self._paused_until.strftime("%H:%M ngày %d/%m/%Y")
        return ""

    # ------------------------------------------------------------------ #
    #  Methods                                                             #
    # ------------------------------------------------------------------ #

    def next_key(self) -> str | None:
        """
        Trả về key tiếp theo có thể dùng (round-robin).
        Trả về None nếu không có key nào khả dụng.
        """
        if not self.available:
            return None
        n = len(self._keys)
        for _ in range(n):
            key = self._keys[self._index % n]
            self._index = (self._index + 1) % n
            if key not in self._exhausted:
                return key
        return None

    def mark_exhausted(self, key: str) -> None:
        """
        Đánh dấu một key bị 429.
        Nếu tất cả key đều exhausted → tạm dừng đến 00:05 hôm sau.
        """
        self._exhausted.add(key)
        if len(self._exhausted) >= len(self._keys):
            tomorrow = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(
                hour=0, minute=5, second=0, microsecond=0
            )
            self._paused_until = tomorrow
            print(
                f"\n  ⚠️  Tất cả {len(self._keys)} Gemini API keys đều bị 429. "
                f"Tạm dừng gọi AI đến {tomorrow.strftime('%H:%M %d/%m/%Y')}.",
                flush=True,
            )

    def reset_key(self, key: str) -> None:
        """Xóa trạng thái exhausted của một key khi gọi thành công."""
        self._exhausted.discard(key)



# Singleton manager
_key_manager = _GeminiKeyManager(GEMINI_API_KEYS)


def call_gemini(prompt: str) -> str:
    """Gom chung logic vong lap round-robin va try/catch 429 / 503 transient errors."""
    if not GEMINI_API_KEYS:
        return "[Warning] Chua cau hinh GEMINI_API_KEY trong file .env. Bo qua phan tich AI."

    if not _key_manager.available:
        pause_time = _key_manager.pause_info
        return f"[Tạm dừng] Tất cả {len(GEMINI_API_KEYS)} Gemini API keys đều đã vượt quota hôm nay. Sẽ thử lại lúc {pause_time}."

    while _key_manager.available:
        api_key = _key_manager.next_key()
        if api_key is None:
            break

        key_label = f"...{api_key[-4:]}" if api_key and len(api_key) >= 4 else "..."
        max_503_retries = 3
        for attempt in range(max_503_retries):
            try:
                if attempt == 0:
                    print(f"  [Gemini] Dùng key [{key_label}]...", flush=True)
                else:
                    print(f"  [Gemini] Thử lại 503 lần {attempt}/{max_503_retries - 1}...", flush=True)
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                _key_manager.reset_key(api_key)
                return response.text if response.text else "Khong nhan duoc phan hoi tu Gemini AI."
            except Exception as api_err:
                err_str = str(api_err)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    wait_sec = _parse_retry_delay(err_str)
                    print(f"  [429] Key [{key_label}] hết quota (retry ~{wait_sec}s). Chuyển key tiếp theo...", flush=True)
                    _key_manager.mark_exhausted(api_key)
                    break
                elif any(code in err_str for code in ("503", "UNAVAILABLE", "500", "502", "504", "ServiceUnavailable")):
                    if attempt < max_503_retries - 1:
                        backoff = (2 ** attempt) + random.uniform(0.1, 0.5)
                        print(f"  [503] Key [{key_label}] tạm thời không khả dụng, chờ {backoff:.1f}s trước khi thử lại...", flush=True)
                        time.sleep(backoff)
                        continue
                    else:
                        print(f"  [503] Key [{key_label}] 503 UNAVAILABLE sau {max_503_retries} lần thử. Trả kết quả degraded.", flush=True)
                        return "[Degraded] Gemini API 503 UNAVAILABLE (dịch vụ tạm thời quá tải). Bỏ qua phân tích AI."
                else:
                    print(f"  [Gemini Error] Key [{key_label}] gặp lỗi: {type(api_err).__name__}", flush=True)
                    return f"[Degraded] Gemini API gặp lỗi: {type(api_err).__name__}. Bỏ qua phân tích AI."

    pause_time = _key_manager.pause_info
    return f"[Tạm dừng] Tất cả {len(GEMINI_API_KEYS)} Gemini API keys đều đã vượt quota hôm nay. Sẽ thử lại lúc {pause_time}."
