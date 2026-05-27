"""Small shared formatting helpers."""

from __future__ import annotations

from typing import Iterable


def format_numbers(numbers: Iterable[int]) -> str:
    return " ".join(f"{int(n):02d}" for n in numbers)

