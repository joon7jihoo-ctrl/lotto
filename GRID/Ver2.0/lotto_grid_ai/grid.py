"""7x7 grid coordinate mapping helpers."""

from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

import numpy as np

from .models import GRID_SIZE, NUMBER_MAX


class GridMapper:
    """
    1~45를 7x7 격자에 좌상단부터 가로 7개씩 배치합니다.

    1  2  3  4  5  6  7
    8  9 10 11 12 13 14
    ...
    43 44 45 [빈칸] [빈칸] [빈칸] [빈칸]
    """

    @staticmethod
    def number_to_pos(number: int) -> Tuple[int, int]:
        if number < 1 or number > 45:
            raise ValueError(f"격자에 매핑할 수 없는 번호입니다: {number}")
        zero_index = number - 1
        return zero_index // GRID_SIZE, zero_index % GRID_SIZE

    @staticmethod
    def pos_to_number(row: int, col: int) -> Optional[int]:
        if row < 0 or row >= GRID_SIZE or col < 0 or col >= GRID_SIZE:
            return None
        number = row * GRID_SIZE + col + 1
        return number if number <= NUMBER_MAX else None

    @classmethod
    def empty_grid(cls, fill_value: float = np.nan) -> np.ndarray:
        grid = np.full((GRID_SIZE, GRID_SIZE), fill_value, dtype=float)
        return grid

    @classmethod
    def numbers_to_grid(cls, values: Dict[int, float], fill_value: float = np.nan) -> np.ndarray:
        grid = cls.empty_grid(fill_value)
        for number, value in values.items():
            row, col = cls.number_to_pos(number)
            grid[row, col] = float(value)
        return grid

    @classmethod
    def neighbors8(cls, number: int) -> Set[int]:
        """
        Layer 3: 직전사각수 알고리즘
        - 직전 회차 번호를 중심점으로 삼음
        - 상/하/좌/우/대각선 8방향 인접 셀을 탐색
        - 46~49에 해당하는 빈칸은 자동 제외
        """
        row, col = cls.number_to_pos(number)
        result: Set[int] = set()

        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                candidate = cls.pos_to_number(row + dr, col + dc)
                if candidate is not None:
                    result.add(candidate)

        return result


