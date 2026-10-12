"""Enkel ratebegränsning för publik drift: per sessions och globalt per dygn (i minnet)."""
import threading
import time
from datetime import datetime, timezone

MAX_QUESTION_CHARS = 300


class RateLimiter:
    def __init__(self, per_session_max=15, min_interval_s=5.0, global_daily_max=300):
        self.per_session_max = per_session_max
        self.min_interval_s = min_interval_s
        self.global_daily_max = global_daily_max
        self._lock = threading.Lock()
        self._day = self._today()
        self._global_count = 0

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def check(self, session_state: dict) -> str | None:
        """Returnerar ett felmeddelande om frågan ska nekas, annars None (och räknar frågan)."""
        now = time.monotonic()
        with self._lock:
            if self._day != self._today():
                self._day = self._today()
                self._global_count = 0
            if self._global_count >= self.global_daily_max:
                return "Demon har nått sin dagliga gräns. Försök igen imorgon."
            if session_state.get("rl_count", 0) >= self.per_session_max:
                return "Du har nått gränsen för antal frågor i den här sessionen."
            last = session_state.get("rl_last")
            if last is not None and now - last < self.min_interval_s:
                return "Vänta några sekunder innan nästa fråga."
            session_state["rl_count"] = session_state.get("rl_count", 0) + 1
            session_state["rl_last"] = now
            self._global_count += 1
        return None
