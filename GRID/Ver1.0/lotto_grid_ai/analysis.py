"""Scoring, candidate-pool construction, and rolling backtests."""

from __future__ import annotations

from math import comb
from typing import List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

from .grid import GridMapper
from .models import (
    NUMBER_MAX,
    NUMBER_MIN,
    AnalysisConfig,
    AnalysisResult,
    BacktestSummary,
    LottoAnalysisError,
    LottoDraw,
)


class LottoAnalyzer:
    """로또 번호 히스토리에서 점수, 후보군, 무작위 대비 백테스트 요약을 산출합니다."""

    RECENT_WINDOWS: Tuple[Tuple[int, float], ...] = (
        (5, 0.35),
        (10, 0.25),
        (20, 0.20),
        (50, 0.12),
        (100, 0.08),
    )

    def analyze(
        self,
        df: pd.DataFrame,
        config: AnalysisConfig,
        source_name: str,
        warnings: Optional[List[str]] = None,
    ) -> AnalysisResult:
        if df is None or df.empty:
            raise LottoAnalysisError("분석할 당첨 번호 데이터가 없습니다.")

        clean_df = df.sort_values("draw_no").reset_index(drop=True).copy()
        latest_draw = self._latest_draw(clean_df)
        (
            score_table,
            prev_square_numbers,
            deadzone_numbers,
        ) = self._score_table(clean_df, latest_draw.numbers, config)
        final_expected_numbers = self._top_expected_numbers(score_table, config)
        candidate_pool = self._layer7_mix_previous_and_expected(
            latest_numbers=latest_draw.numbers,
            final_expected_numbers=final_expected_numbers,
            score_table=score_table,
            config=config,
        )
        backtest_summary = self._backtest_candidate_pool(clean_df, config)

        return AnalysisResult(
            df=clean_df,
            latest_draw=latest_draw,
            score_table=score_table,
            prev_square_numbers=prev_square_numbers,
            deadzone_numbers=deadzone_numbers,
            final_expected_numbers=final_expected_numbers,
            candidate_pool=candidate_pool,
            source_name=source_name,
            backtest_summary=backtest_summary,
            warnings=warnings or [],
        )

    def _latest_draw(self, df: pd.DataFrame) -> LottoDraw:
        latest_row = df.iloc[-1]
        latest_numbers = self._row_numbers(latest_row)
        return LottoDraw(
            draw_no=int(latest_row["draw_no"]),
            draw_date=str(latest_row.get("date", "")),
            numbers=latest_numbers,  # type: ignore[arg-type]
            bonus=int(latest_row["bonus"]) if pd.notna(latest_row.get("bonus", np.nan)) else None,
        )

    def _score_table(
        self,
        df: pd.DataFrame,
        latest_numbers: Sequence[int],
        config: AnalysisConfig,
    ) -> Tuple[pd.DataFrame, Set[int], Set[int]]:
        freq_score, freq_counts = self._layer2_frequency_score(df)
        missing_score, missing_gap = self._layer2_missing_score(df)
        square_score, prev_square_numbers, square_hit_count = self._layer3_previous_square(latest_numbers)
        deadzone_score, deadzone_numbers, deadzone_recent_counts = self._layer4_deadzone(
            df, config.deadzone_window
        )
        composite_score = self._layer5_composite(
            freq_score=freq_score,
            missing_score=missing_score,
            square_score=square_score,
            deadzone_score=deadzone_score,
            config=config,
        )
        table = self._build_score_table(
            composite_score=composite_score,
            freq_score=freq_score,
            freq_counts=freq_counts,
            missing_score=missing_score,
            missing_gap=missing_gap,
            square_score=square_score,
            square_hit_count=square_hit_count,
            deadzone_score=deadzone_score,
            deadzone_recent_counts=deadzone_recent_counts,
            prev_square_numbers=prev_square_numbers,
            deadzone_numbers=deadzone_numbers,
            latest_numbers=latest_numbers,
        )
        return table, prev_square_numbers, deadzone_numbers

    @staticmethod
    def _build_score_table(
        composite_score: np.ndarray,
        freq_score: np.ndarray,
        freq_counts: np.ndarray,
        missing_score: np.ndarray,
        missing_gap: np.ndarray,
        square_score: np.ndarray,
        square_hit_count: np.ndarray,
        deadzone_score: np.ndarray,
        deadzone_recent_counts: np.ndarray,
        prev_square_numbers: Set[int],
        deadzone_numbers: Set[int],
        latest_numbers: Sequence[int],
    ) -> pd.DataFrame:
        numbers = np.arange(1, NUMBER_MAX + 1)
        latest_set = set(latest_numbers)
        return pd.DataFrame(
            {
                "number": numbers,
                "score": composite_score,
                "freq_score": freq_score * 100.0,
                "freq_recent_count": freq_counts,
                "missing_score": missing_score * 100.0,
                "missing_gap": missing_gap,
                "square_score": square_score * 100.0,
                "square_hit_count": square_hit_count,
                "deadzone_score": deadzone_score * 100.0,
                "deadzone_recent_count": deadzone_recent_counts,
                "is_prev_square": [n in prev_square_numbers for n in numbers],
                "is_deadzone": [n in deadzone_numbers for n in numbers],
                "is_latest": [n in latest_set for n in numbers],
            }
        ).sort_values(["score", "number"], ascending=[False, True]).reset_index(drop=True)

    @staticmethod
    def _top_expected_numbers(score_table: pd.DataFrame, config: AnalysisConfig) -> List[int]:
        top_n = int(np.clip(config.top_candidate_count, 6, NUMBER_MAX))
        return score_table.head(top_n)["number"].astype(int).tolist()

    # -----------------------------
    # Layer 2-A: 기간별 빈도 분석
    # -----------------------------
    def _layer2_frequency_score(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        기간별 출현 빈도:
        - 최근 5/10/20/50/100회차를 서로 다른 가중치로 결합
        - 단기 과열 번호와 중기 안정 번호를 동시에 반영
        - 최종 값은 0~1로 정규화
        """
        weighted = np.zeros(NUMBER_MAX, dtype=float)
        short_count_for_ui = np.zeros(NUMBER_MAX, dtype=int)

        for window, weight in self.RECENT_WINDOWS:
            sub = df.tail(min(window, len(df)))
            counts = self._count_numbers(sub)
            weighted += self._minmax(counts) * weight

            if window == 20:
                short_count_for_ui = counts.astype(int)

        return self._minmax(weighted), short_count_for_ui

    # -----------------------------
    # Layer 2-B: 장기 미출수 추적
    # -----------------------------
    def _layer2_missing_score(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        장기 미출수:
        - 각 번호의 마지막 출현 회차를 추적
        - 최신 회차와의 차이를 missing_gap으로 계산
        - 오래 나오지 않은 번호일수록 높은 점수
        """
        latest_draw_no = int(df["draw_no"].max())
        first_draw_no = int(df["draw_no"].min())
        last_seen = np.full(NUMBER_MAX, first_draw_no - 1, dtype=int)

        for _, row in df.iterrows():
            draw_no = int(row["draw_no"])
            for number in self._row_numbers(row):
                last_seen[number - 1] = draw_no

        missing_gap = latest_draw_no - last_seen
        return self._minmax(missing_gap), missing_gap

    # -----------------------------
    # Layer 3: 직전사각수 알고리즘
    # -----------------------------
    def _layer3_previous_square(
        self,
        latest_numbers: Sequence[int],
    ) -> Tuple[np.ndarray, Set[int], np.ndarray]:
        """
        직전 회차 번호를 7x7 격자에 매핑한 뒤, 각 번호의 8방향 인접 번호를 추출합니다.

        수학적 해석:
        - 각 당첨 번호 p=(r,c)에 대해 N8(p) = {(r+i,c+j), i,j∈{-1,0,1}, (i,j)!=(0,0)}
        - 격자 밖과 46~49 빈칸은 제외
        - 여러 중심 번호의 주변으로 중복 등장한 번호는 square_hit_count가 증가
        """
        counts = np.zeros(NUMBER_MAX, dtype=float)
        prev_square_numbers: Set[int] = set()

        for center in latest_numbers:
            for neighbor in GridMapper.neighbors8(int(center)):
                counts[neighbor - 1] += 1.0
                prev_square_numbers.add(neighbor)

        return self._minmax(counts), prev_square_numbers, counts.astype(int)

    # -----------------------------
    # Layer 4: 완전사각/데드존 추적
    # -----------------------------
    def _layer4_deadzone(
        self,
        df: pd.DataFrame,
        window: int,
    ) -> Tuple[np.ndarray, Set[int], np.ndarray]:
        """
        최근 N회차 동안 7x7 공간에서 출현 빈도가 0인 번호를 감지합니다.

        이 구현에서는 번호 단위의 deadzone을 사용합니다.
        즉, 최근 N회차 전체에서 한 번도 나오지 않은 번호를 완전사각/소외 구역으로 표시합니다.
        """
        window = int(np.clip(window, 1, max(1, len(df))))
        recent = df.tail(window)
        counts = self._count_numbers(recent).astype(int)

        deadzone_numbers = {n for n in range(1, NUMBER_MAX + 1) if counts[n - 1] == 0}
        score = np.zeros(NUMBER_MAX, dtype=float)
        for n in deadzone_numbers:
            score[n - 1] = 1.0

        return score, deadzone_numbers, counts

    # -----------------------------
    # Layer 5: 종합 가중치 매트릭스
    # -----------------------------
    def _layer5_composite(
        self,
        freq_score: np.ndarray,
        missing_score: np.ndarray,
        square_score: np.ndarray,
        deadzone_score: np.ndarray,
        config: AnalysisConfig,
    ) -> np.ndarray:
        """
        Layer 2~4에서 나온 서로 다른 성격의 점수를 하나의 0~100 점수로 합성합니다.

        가중치가 모두 0이면 모든 레이어를 균등 가중치로 처리해 빈 결과를 방지합니다.
        """
        weights = np.array(
            [
                max(0, config.recent_weight),
                max(0, config.missing_weight),
                max(0, config.square_weight),
                max(0, config.deadzone_weight),
            ],
            dtype=float,
        )

        if np.isclose(weights.sum(), 0.0):
            weights = np.ones_like(weights)

        weights = weights / weights.sum()
        raw = (
            freq_score * weights[0]
            + missing_score * weights[1]
            + square_score * weights[2]
            + deadzone_score * weights[3]
        )

        return self._minmax(raw) * 100.0

    # -----------------------------
    # Layer 7: 이전당첨 + 예상수 믹서
    # -----------------------------
    def _layer7_mix_previous_and_expected(
        self,
        latest_numbers: Sequence[int],
        final_expected_numbers: Sequence[int],
        score_table: pd.DataFrame,
        config: AnalysisConfig,
    ) -> List[int]:
        """
        직전 회차 번호(이월수 후보)와 Layer 6 예상수를 사용자가 설정한 비율로 융합합니다.

        예:
        - 후보군 N=20, 믹스 25% -> 직전 회차에서 최대 5칸을 우선 확보
        - 남은 칸은 종합 점수 상위 예상수로 채움
        - 중복 제거 후 점수 순으로 부족분을 보충
        """
        top_n = int(np.clip(config.top_candidate_count, 6, NUMBER_MAX))
        score_map = {
            int(row["number"]): float(row["score"])
            for _, row in score_table.iterrows()
        }

        previous_slots = int(round(top_n * np.clip(config.mix_previous_ratio, 0, 100) / 100.0))
        previous_slots = int(np.clip(previous_slots, 0, min(6, top_n)))
        expected_slots = max(0, top_n - previous_slots)

        latest_sorted = sorted(
            [int(n) for n in latest_numbers],
            key=lambda n: score_map.get(n, 0.0),
            reverse=True,
        )

        pool: List[int] = []

        def push(number: int) -> None:
            if NUMBER_MIN <= number <= NUMBER_MAX and number not in pool:
                pool.append(number)

        for n in latest_sorted[:previous_slots]:
            push(n)

        for n in final_expected_numbers[:expected_slots]:
            push(int(n))

        # 중복으로 인해 후보군이 모자랄 수 있으므로 전체 점수표에서 보충.
        for n in score_table["number"].astype(int).tolist():
            if len(pool) >= top_n:
                break
            push(n)

        return pool[:top_n]

    def _backtest_candidate_pool(self, df: pd.DataFrame, config: AnalysisConfig) -> BacktestSummary:
        """
        현재 레이어 조합이 다음 회차 번호를 후보군 안에 얼마나 담는지 롤링 방식으로 점검합니다.
        이는 당첨 보장이 아니라 무작위 후보군 대비 현재 휴리스틱이 의미 있는지 보는 안전장치입니다.
        """
        if df is None or len(df) < 30:
            return BacktestSummary()

        rounds = int(np.clip(config.backtest_rounds, 0, 300))
        if rounds <= 0:
            return BacktestSummary()

        train_window = int(np.clip(config.backtest_train_window, 20, max(20, len(df) - 1)))
        start_idx = max(train_window, len(df) - rounds)
        hit_counts: List[int] = []

        for idx in range(start_idx, len(df)):
            train = df.iloc[max(0, idx - train_window):idx].copy()
            target_numbers = set(self._row_numbers(df.iloc[idx]))
            pool = self._candidate_pool_for_training(train, config)
            hit_counts.append(len(target_numbers & set(pool)))

        if not hit_counts:
            return BacktestSummary()

        candidate_count = int(np.clip(config.top_candidate_count, 6, NUMBER_MAX))
        random_avg_hits = 6.0 * candidate_count / NUMBER_MAX
        return BacktestSummary(
            rounds=len(hit_counts),
            train_window=train_window,
            candidate_count=candidate_count,
            avg_hits=float(np.mean(hit_counts)),
            random_avg_hits=random_avg_hits,
            hit3_rate=self._rate_at_least(hit_counts, 3),
            random_hit3_rate=self._hypergeom_at_least(candidate_count, 3),
            hit4_rate=self._rate_at_least(hit_counts, 4),
            random_hit4_rate=self._hypergeom_at_least(candidate_count, 4),
            best_hit_count=int(max(hit_counts)),
            last_hit_count=int(hit_counts[-1]),
        )

    def _candidate_pool_for_training(self, train: pd.DataFrame, config: AnalysisConfig) -> List[int]:
        if train is None or train.empty:
            return []

        latest_numbers = self._row_numbers(train.iloc[-1])
        freq_score, freq_counts = self._layer2_frequency_score(train)
        missing_score, _missing_gap = self._layer2_missing_score(train)
        square_score, _prev_square_numbers, _square_hit_count = self._layer3_previous_square(latest_numbers)
        deadzone_score, _deadzone_numbers, _deadzone_recent_counts = self._layer4_deadzone(
            train, config.deadzone_window
        )
        composite_score = self._layer5_composite(
            freq_score=freq_score,
            missing_score=missing_score,
            square_score=square_score,
            deadzone_score=deadzone_score,
            config=config,
        )
        numbers = np.arange(1, NUMBER_MAX + 1)
        score_table = pd.DataFrame(
            {
                "number": numbers,
                "score": composite_score,
                "freq_recent_count": freq_counts,
            }
        ).sort_values(["score", "number"], ascending=[False, True]).reset_index(drop=True)

        top_n = int(np.clip(config.top_candidate_count, 6, NUMBER_MAX))
        final_expected_numbers = score_table.head(top_n)["number"].astype(int).tolist()
        return self._layer7_mix_previous_and_expected(
            latest_numbers=latest_numbers,
            final_expected_numbers=final_expected_numbers,
            score_table=score_table,
            config=config,
        )

    @staticmethod
    def _rate_at_least(values: Sequence[int], minimum: int) -> float:
        if not values:
            return 0.0
        return sum(1 for value in values if int(value) >= minimum) / len(values)

    @staticmethod
    def _hypergeom_at_least(candidate_count: int, minimum_hits: int) -> float:
        candidate_count = int(np.clip(candidate_count, 0, NUMBER_MAX))
        total_cases = comb(NUMBER_MAX, 6)
        max_hits = min(6, candidate_count)
        probability = 0.0
        for hits in range(minimum_hits, max_hits + 1):
            if 6 - hits > NUMBER_MAX - candidate_count:
                continue
            probability += comb(candidate_count, hits) * comb(NUMBER_MAX - candidate_count, 6 - hits)
        return probability / total_cases if total_cases else 0.0

    @staticmethod
    def _row_numbers(row: pd.Series) -> Tuple[int, int, int, int, int, int]:
        return tuple(int(row[f"n{i}"]) for i in range(1, 7))  # type: ignore[return-value]

    @classmethod
    def _count_numbers(cls, df: pd.DataFrame) -> np.ndarray:
        counts = np.zeros(NUMBER_MAX, dtype=float)
        if df is None or df.empty:
            return counts

        for _, row in df.iterrows():
            for number in cls._row_numbers(row):
                counts[number - 1] += 1.0

        return counts

    @staticmethod
    def _minmax(values: Sequence[float]) -> np.ndarray:
        arr = np.asarray(values, dtype=float)
        if arr.size == 0:
            return arr

        min_v = np.nanmin(arr)
        max_v = np.nanmax(arr)

        if not np.isfinite(min_v) or not np.isfinite(max_v) or np.isclose(max_v, min_v):
            return np.zeros_like(arr, dtype=float)

        return (arr - min_v) / (max_v - min_v)


