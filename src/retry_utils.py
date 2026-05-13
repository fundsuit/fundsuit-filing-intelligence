from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 20.0
    jitter_seconds: float = 0.25

    @classmethod
    def from_env(cls) -> "RetryConfig":
        return cls(
            max_attempts=max(1, int(os.getenv("PIPELINE_MAX_RETRIES", "3"))),
            initial_delay_seconds=max(0.0, float(os.getenv("PIPELINE_INITIAL_BACKOFF_SECONDS", "1.0"))),
            backoff_multiplier=max(1.0, float(os.getenv("PIPELINE_BACKOFF_MULTIPLIER", "2.0"))),
            max_delay_seconds=max(0.0, float(os.getenv("PIPELINE_MAX_BACKOFF_SECONDS", "20.0"))),
            jitter_seconds=max(0.0, float(os.getenv("PIPELINE_JITTER_SECONDS", "0.25"))),
        )


def retry_with_backoff(
    operation: Callable[[], T],
    *,
    operation_name: str,
    config: RetryConfig,
) -> T:
    delay = config.initial_delay_seconds
    for attempt in range(1, config.max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if attempt >= config.max_attempts:
                raise
            jitter = random.uniform(0, config.jitter_seconds) if config.jitter_seconds else 0.0
            wait_seconds = min(config.max_delay_seconds, delay) + jitter
            print(
                f"[WARN] {operation_name} attempt {attempt}/{config.max_attempts} failed: {exc}. "
                f"Retrying in {wait_seconds:.2f}s."
            )
            time.sleep(wait_seconds)
            delay = min(config.max_delay_seconds, delay * config.backoff_multiplier)

    raise RuntimeError(f"{operation_name} failed unexpectedly without returning or raising.")

