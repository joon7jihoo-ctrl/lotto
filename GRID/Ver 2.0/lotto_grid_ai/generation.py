"""Combination generation, diversity filtering, pattern checks, and prize checking."""

from __future__ import annotations

import heapq
import itertools
from math import comb, exp
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

from .models import (
    NUMBER_MAX,
    AnalysisConfig,
    AnalysisResult,
    CombinationRecord,
    LottoAnalysisError,
    WinningCheckRecord,
)


OPTIMAL_SUM_MIN = 100
OPTIMAL_SUM_MAX = 170
BALANCED_COUNT_RANGE = {2, 3, 4}


def filter_by_sum(combination: Sequence[int]) -> bool:
    # 총합 필터: 역대 로또 조합에서 자주 관찰되는 100~170 구간만 통과시킵니다.
    numbers = _normalized_combination(combination)
    return bool(numbers) and OPTIMAL_SUM_MIN <= sum(numbers) <= OPTIMAL_SUM_MAX


def filter_by_odd_even(combination: Sequence[int]) -> bool:
    # 홀짝 필터: 3:3, 2:4, 4:2처럼 한쪽으로 치우치지 않은 조합만 통과시킵니다.
    numbers = _normalized_combination(combination)
    if not numbers:
        return False
    odd_count = sum(1 for number in numbers if number % 2 == 1)
    return odd_count in BALANCED_COUNT_RANGE


def filter_by_high_low(combination: Sequence[int]) -> bool:
    # 고저 필터: 1~22와 23~45의 분포가 3:3, 2:4, 4:2인 조합만 통과시킵니다.
    numbers = _normalized_combination(combination)
    if not numbers:
        return False
    high_count = sum(1 for number in numbers if number >= 23)
    return high_count in BALANCED_COUNT_RANGE


def filter_by_consecutive(combination: Sequence[int]) -> bool:
    # 연번 필터: 3연번 이상은 제외하고, 최대 2연번까지만 허용합니다.
    numbers = _normalized_combination(combination)
    if not numbers:
        return False

    current_run = 1
    for prev, current in zip(numbers, numbers[1:]):
        if current == prev + 1:
            current_run += 1
            if current_run >= 3:
                return False
        else:
            current_run = 1
    return True


def filter_by_zone_diversity(combination: Sequence[int]) -> bool:
    # 구간 다양성 필터: 6개 번호가 최소 3개 이상의 구간에서 선택되어야 합니다.
    # 구간: 1-9, 10-19, 20-29, 30-39, 40-45
    numbers = _normalized_combination(combination)
    if not numbers:
        return False
    zones: set = set()
    for n in numbers:
        if n <= 9:    zones.add(0)
        elif n <= 19: zones.add(1)
        elif n <= 29: zones.add(2)
        elif n <= 39: zones.add(3)
        else:         zones.add(4)
    return len(zones) >= 3


def filter_by_last_digit_diversity(combination: Sequence[int]) -> bool:
    # 끝자리 다양성 필터: 역대 로또 94%가 끝자리 4개 이상 다름.
    # 생일수/연속수 패턴과 함께 인기 조합 회피 효과.
    numbers = _normalized_combination(combination)
    if not numbers:
        return False
    last_digits = {n % 10 for n in numbers}
    return len(last_digits) >= 4


def _normalized_combination(combination: Sequence[int]) -> Tuple[int, ...]:
    # 필터 입력을 정렬된 6개 고유 번호로 정규화합니다. 유효하지 않으면 빈 튜플을 반환합니다.
    try:
        numbers = tuple(sorted(int(number) for number in combination))
    except (TypeError, ValueError):
        return tuple()
    if len(numbers) != 6 or len(set(numbers)) != 6:
        return tuple()
    if any(number < 1 or number > NUMBER_MAX for number in numbers):
        return tuple()
    return numbers


class CombinationGenerator:
    """수학 필터, 인기 패턴 회피, 조합 다양성 조건을 만족하는 6개 조합을 생성합니다."""

    MAX_POOL_FOR_FULL_SEARCH = 28
    RANDOM_PREFILTER_MIN_TRIALS = 2_000
    RANDOM_PREFILTER_PER_OUTPUT = 500
    RANDOM_PREFILTER_MAX_TRIALS = 150_000

    def generate(
        self,
        analysis: AnalysisResult,
        config: AnalysisConfig,
    ) -> Tuple[List[CombinationRecord], List[str]]:
        warnings: List[str] = []
        pool = self._prepare_pool(analysis.candidate_pool, warnings)
        score_map = self._score_map(analysis)
        latest_set = set(int(n) for n in analysis.latest_draw.numbers)
        records = self._search_with_relaxations(
            pool=pool,
            score_map=score_map,
            latest_set=latest_set,
            config=config,
            source_draw_no=analysis.latest_draw.draw_no,
            warnings=warnings,
        )
        self._sort_records(records, config)
        return self._select_output(records, config, warnings), warnings

    def _prepare_pool(self, candidate_pool: Sequence[int], warnings: List[str]) -> List[int]:
        pool = list(dict.fromkeys(int(n) for n in candidate_pool))
        if len(pool) < 6:
            raise LottoAnalysisError("후보 번호가 6개 미만이라 조합을 생성할 수 없습니다.")

        if len(pool) > self.MAX_POOL_FOR_FULL_SEARCH:
            warnings.append(
                f"조합 폭증 방지를 위해 후보군 {len(pool)}개 중 상위 "
                f"{self.MAX_POOL_FOR_FULL_SEARCH}개만 사용했습니다."
            )
            pool = pool[: self.MAX_POOL_FOR_FULL_SEARCH]
        return pool

    @staticmethod
    def _score_map(analysis: AnalysisResult) -> Dict[int, float]:
        return {
            int(row["number"]): float(row["score"])
            for _, row in analysis.score_table.iterrows()
        }

    def _search_with_relaxations(
        self,
        pool: Sequence[int],
        score_map: Dict[int, float],
        latest_set: Set[int],
        config: AnalysisConfig,
        source_draw_no: int,
        warnings: List[str],
    ) -> List[CombinationRecord]:
        records = self._search(
            pool,
            score_map,
            latest_set,
            config,
            enforce_carry=True,
            source_draw_no=source_draw_no,
            max_pattern_risk=config.max_popularity_risk,
        )

        if records:
            return records

        warnings.append("이월수 믹스 조건까지 만족하는 조합이 없어 믹스 조건만 완화해 재탐색했습니다.")
        records = self._search(
            pool,
            score_map,
            latest_set,
            config,
            enforce_carry=False,
            source_draw_no=source_draw_no,
            max_pattern_risk=config.max_popularity_risk,
        )
        if records:
            return records

        relaxed_risk = min(10, config.max_popularity_risk + 2)
        warnings.append(f"인기 패턴 회피 조건을 {relaxed_risk}점까지 완화해 재탐색했습니다.")
        return self._search(
            pool,
            score_map,
            latest_set,
            config,
            enforce_carry=False,
            source_draw_no=source_draw_no,
            max_pattern_risk=relaxed_risk,
        )

    @staticmethod
    def _sort_records(records: List[CombinationRecord], config: AnalysisConfig) -> None:
        records.sort(
            key=lambda r: (
                r.score,
                r.ac_value,
                -r.pattern_risk,
                -abs(r.total - ((config.sum_min + config.sum_max) / 2.0)),
            ),
            reverse=True,
        )

    def _select_output(
        self,
        records: Sequence[CombinationRecord],
        config: AnalysisConfig,
        warnings: List[str],
    ) -> List[CombinationRecord]:
        output_limit = max(1, config.output_limit)
        selected = self._select_diverse(records, output_limit, config.max_overlap)
        if len(selected) < min(output_limit, len(records)):
            relaxed_overlap = min(5, config.max_overlap + 1)
            warnings.append(
                f"조합 간 중복 {config.max_overlap}개 제한으로 출력 수가 부족해 "
                f"{relaxed_overlap}개까지 한 번 완화했습니다."
            )
            selected = self._select_diverse(records, output_limit, relaxed_overlap)

        return selected

    def _search(
        self,
        pool: Sequence[int],
        score_map: Dict[int, float],
        latest_set: Set[int],
        config: AnalysisConfig,
        enforce_carry: bool,
        source_draw_no: int,
        max_pattern_risk: int,
    ) -> List[CombinationRecord]:
        carry_min, carry_max = self._carry_bounds(config)
        keep_limit = max(1000, int(config.output_limit) * 60)
        heap: List[Tuple[float, int, CombinationRecord]] = []
        seen: Set[Tuple[int, int, int, int, int, int]] = set()
        seq = 0

        # 1차: 후보 번호 풀에서 무작위 6개 조합을 만들고 통계 필터를 적용합니다.
        for combo in self._random_candidate_combinations(pool, config.output_limit):
            seen.add(combo)
            seq = self._evaluate_candidate(
                combo=combo,
                seq=seq,
                heap=heap,
                keep_limit=keep_limit,
                score_map=score_map,
                latest_set=latest_set,
                carry_min=carry_min,
                carry_max=carry_max,
                enforce_carry=enforce_carry,
                config=config,
                source_draw_no=source_draw_no,
                max_pattern_risk=max_pattern_risk,
            )

        # 2차: 남은 조합도 보완 탐색해 무작위 표본만으로 좋은 조합을 놓치지 않게 합니다.
        for combo in itertools.combinations(sorted(pool), 6):
            if combo in seen:
                continue
            seq = self._evaluate_candidate(
                combo=combo,
                seq=seq,
                heap=heap,
                keep_limit=keep_limit,
                score_map=score_map,
                latest_set=latest_set,
                carry_min=carry_min,
                carry_max=carry_max,
                enforce_carry=enforce_carry,
                config=config,
                source_draw_no=source_draw_no,
                max_pattern_risk=max_pattern_risk,
            )

        return [record for _score, _seq, record in heap]

    def _random_candidate_combinations(
        self,
        pool: Sequence[int],
        output_limit: int,
    ) -> List[Tuple[int, int, int, int, int, int]]:
        # 출력 개수 N에 맞춰 무작위 후보 조합을 만들고, 중복 조합은 제거합니다.
        numbers = tuple(sorted(int(number) for number in pool))
        total_cases = comb(len(numbers), 6)
        trial_limit = self._random_trial_limit(total_cases, output_limit)
        rng = np.random.default_rng()

        if total_cases <= trial_limit:
            combos = list(itertools.combinations(numbers, 6))
            rng.shuffle(combos)
            return combos

        selected: Set[Tuple[int, int, int, int, int, int]] = set()
        while len(selected) < trial_limit:
            combo = tuple(sorted(int(n) for n in rng.choice(numbers, size=6, replace=False)))
            selected.add(combo)  # type: ignore[arg-type]
        return list(selected)

    def _random_trial_limit(self, total_cases: int, output_limit: int) -> int:
        # 무작위 생성량은 N에 비례시키되, 앱 반응성을 위해 상한을 둡니다.
        requested = max(
            self.RANDOM_PREFILTER_MIN_TRIALS,
            int(output_limit) * self.RANDOM_PREFILTER_PER_OUTPUT,
        )
        requested = min(requested, self.RANDOM_PREFILTER_MAX_TRIALS)
        return max(1, min(total_cases, requested))

    def _evaluate_candidate(
        self,
        combo: Tuple[int, int, int, int, int, int],
        seq: int,
        heap: List[Tuple[float, int, CombinationRecord]],
        keep_limit: int,
        score_map: Dict[int, float],
        latest_set: Set[int],
        carry_min: int,
        carry_max: int,
        enforce_carry: bool,
        config: AnalysisConfig,
        source_draw_no: int,
        max_pattern_risk: int,
    ) -> int:
        # 통계 필터와 기존 점수화 로직을 모두 통과한 조합만 최종 후보로 보관합니다.
        metrics = self._combo_metrics(combo)
        if not self._passes_math_filters(combo, metrics, config):
            return seq + 1

        carry_count = sum(1 for n in combo if n in latest_set)
        if enforce_carry and not (carry_min <= carry_count <= carry_max):
            return seq + 1

        pattern_risk, pattern_notes = self.popularity_risk(combo)
        if pattern_risk > max_pattern_risk:
            return seq + 1

        record = self._build_record(
            combo=combo,
            metrics=metrics,
            carry_count=carry_count,
            score_map=score_map,
            config=config,
            source_draw_no=source_draw_no,
            pattern_risk=pattern_risk,
            pattern_notes=pattern_notes,
        )
        self._push_heap_record(heap, record, keep_limit, seq)
        return seq + 1

    @staticmethod
    def _carry_bounds(config: AnalysisConfig) -> Tuple[int, int]:
        target_carry = int(round(6 * np.clip(config.mix_previous_ratio, 0, 100) / 100.0))
        if config.mix_previous_ratio <= 5:
            return 0, 1
        if config.mix_previous_ratio >= 95:
            return 5, 6
        return max(0, target_carry - 1), min(6, target_carry + 1)

    def _combo_metrics(self, combo: Sequence[int]) -> Dict[str, int]:
        return {
            "total": sum(combo),
            "odd_count": sum(1 for n in combo if n % 2 == 1),
            "high_count": sum(1 for n in combo if n >= 23),
            "ac_value": self.ac_value(combo),
        }

    @staticmethod
    def _passes_math_filters(
        combo: Sequence[int],
        metrics: Dict[str, int],
        config: AnalysisConfig,
    ) -> bool:
        # 네 가지 통계적 최적화 필터가 모두 True인 조합만 통과시킵니다.
        passed_statistical_filters = all(
            (
                filter_by_sum(combo),
                filter_by_odd_even(combo),
                filter_by_high_low(combo),
                filter_by_consecutive(combo),
                filter_by_zone_diversity(combo),
                filter_by_last_digit_diversity(combo),
            )
        )
        return (
            passed_statistical_filters
            and metrics["ac_value"] >= config.min_ac
        )

    def _build_record(
        self,
        combo: Sequence[int],
        metrics: Dict[str, int],
        carry_count: int,
        score_map: Dict[int, float],
        config: AnalysisConfig,
        source_draw_no: int,
        pattern_risk: int,
        pattern_notes: Sequence[str],
    ) -> CombinationRecord:
        rank_score = self._rank_score(combo, metrics, carry_count, score_map, config, pattern_risk)
        return CombinationRecord(
            numbers=tuple(combo),  # type: ignore[arg-type]
            total=metrics["total"],
            odd_count=metrics["odd_count"],
            high_count=metrics["high_count"],
            ac_value=metrics["ac_value"],
            carry_count=carry_count,
            score=rank_score,
            source_draw_no=source_draw_no,
            pattern_risk=pattern_risk,
            pattern_notes=", ".join(pattern_notes),
        )

    @staticmethod
    def _rank_score(
        combo: Sequence[int],
        metrics: Dict[str, int],
        carry_count: int,
        score_map: Dict[int, float],
        config: AnalysisConfig,
        pattern_risk: int,
    ) -> float:
        score_sum = sum(score_map.get(n, 0.0) for n in combo)
        ideal_sum = (config.sum_min + config.sum_max) / 2.0
        sigma = max(1.0, (config.sum_max - config.sum_min) / 4.0)
        balance_bonus = 20.0 * exp(-0.5 * ((metrics["total"] - ideal_sum) / sigma) ** 2)
        ac_bonus = metrics["ac_value"] * 1.3
        carry_bonus = carry_count * 0.7
        pattern_penalty = pattern_risk * 12.0
        return score_sum + balance_bonus + ac_bonus + carry_bonus - pattern_penalty

    @staticmethod
    def _push_heap_record(
        heap: List[Tuple[float, int, CombinationRecord]],
        record: CombinationRecord,
        keep_limit: int,
        seq: int,
    ) -> None:
        heap_key = record.score
        if len(heap) < keep_limit:
            heapq.heappush(heap, (heap_key, seq, record))
        elif heap_key > heap[0][0]:
            heapq.heapreplace(heap, (heap_key, seq, record))

    def _select_diverse(
        self,
        records: Sequence[CombinationRecord],
        output_limit: int,
        max_overlap: int,
    ) -> List[CombinationRecord]:
        selected: List[CombinationRecord] = []
        max_overlap = int(np.clip(max_overlap, 0, 5))

        for record in records:
            record_set = set(record.numbers)
            if all(len(record_set & set(existing.numbers)) <= max_overlap for existing in selected):
                selected.append(record)
                if len(selected) >= output_limit:
                    break

        return selected

    @staticmethod
    def ac_value(numbers: Sequence[int]) -> int:
        """
        AC값(Arithmetic Complexity):
        - 6개 번호의 모든 쌍 차이를 구함
        - 서로 다른 차이 개수 - (선택 번호 수 - 1)
        - 6개 번호에서는 일반적으로 0~10 범위
        """
        sorted_nums = sorted(int(n) for n in numbers)
        diffs = {
            b - a
            for a, b in itertools.combinations(sorted_nums, 2)
        }
        return len(diffs) - (len(sorted_nums) - 1)

    @classmethod
    def popularity_risk(cls, numbers: Sequence[int]) -> Tuple[int, List[str]]:
        """
        당첨 확률 자체가 아니라 당첨 시 나눠 가질 가능성이 높은 흔한 패턴을 점수화합니다.
        위험 점수가 높을수록 생일수/연속수/끝수 몰림/등차 패턴에 가깝습니다.
        """
        nums = sorted(int(n) for n in numbers)
        risk = 0
        notes: List[str] = []

        under_31 = sum(1 for n in nums if n <= 31)
        if under_31 == 6:
            risk += 3
            notes.append("생일수")
        elif under_31 >= 5:
            risk += 2
            notes.append("생일수 과다")

        max_run = cls._max_consecutive_run(nums)
        if max_run >= 4:
            risk += 3
            notes.append("연속수 과다")
        elif max_run == 3:
            risk += 1
            notes.append("3연속")

        last_digit_counts: Dict[int, int] = {}
        for n in nums:
            last_digit_counts[n % 10] = last_digit_counts.get(n % 10, 0) + 1
        if max(last_digit_counts.values(), default=0) >= 3:
            risk += 2
            notes.append("끝수 몰림")

        if cls._has_arithmetic_subsequence(nums, length=4):
            risk += 2
            notes.append("등차 패턴")

        return risk, notes

    @staticmethod
    def _max_consecutive_run(numbers: Sequence[int]) -> int:
        if not numbers:
            return 0

        best = 1
        current = 1
        for prev, current_number in zip(numbers, numbers[1:]):
            if int(current_number) == int(prev) + 1:
                current += 1
            else:
                best = max(best, current)
                current = 1
        return max(best, current)

    @staticmethod
    def _has_arithmetic_subsequence(numbers: Sequence[int], length: int = 4) -> bool:
        nums = sorted(int(n) for n in numbers)
        for subset in itertools.combinations(nums, length):
            diffs = [b - a for a, b in zip(subset, subset[1:])]
            if diffs and len(set(diffs)) == 1:
                return True
        return False


class LottoPrizeChecker:
    """생성된 조합을 생성 기준 회차 이후 당첨 이력과 비교합니다."""

    def check(
        self,
        records: Sequence[CombinationRecord],
        df: pd.DataFrame,
        source_draw_no: Optional[int] = None,
    ) -> List[WinningCheckRecord]:
        if df is None or df.empty:
            raise LottoAnalysisError("당첨 여부를 확인할 회차 데이터가 없습니다.")

        checked: List[WinningCheckRecord] = []
        for record in records:
            record_source_draw_no = record.source_draw_no if record.source_draw_no is not None else source_draw_no
            checked.append(self._best_match(record.numbers, df, record_source_draw_no))
        return checked

    def _best_match(
        self,
        numbers: Sequence[int],
        df: pd.DataFrame,
        source_draw_no: Optional[int],
    ) -> WinningCheckRecord:
        combo_set = set(int(n) for n in numbers)
        compare_df = df.copy()
        if source_draw_no is not None:
            compare_df = compare_df[compare_df["draw_no"].astype(int) > int(source_draw_no)]

        best_key = (-1, -1, 0, -1)
        best_record = WinningCheckRecord(
            numbers=tuple(sorted(combo_set)),  # type: ignore[arg-type]
            draw_no=None,
            draw_date="",
            match_count=0,
            bonus_match=False,
            rank="대기" if compare_df.empty else "낙첨",
            matched_numbers=tuple(),
            source_draw_no=source_draw_no,
            checked_draw_count=len(compare_df),
        )

        for _, row in compare_df.iterrows():
            draw_numbers = {int(row[f"n{i}"]) for i in range(1, 7)}
            bonus_raw = row.get("bonus", np.nan)
            bonus = None if pd.isna(bonus_raw) else int(bonus_raw)
            matched = tuple(sorted(combo_set & draw_numbers))
            match_count = len(matched)
            bonus_match = bonus in combo_set if bonus is not None else False
            rank, rank_score = self._rank(match_count, bonus_match)
            draw_no = int(row["draw_no"])
            key = (rank_score, match_count, int(bonus_match), draw_no)

            if key > best_key:
                best_key = key
                best_record = WinningCheckRecord(
                    numbers=tuple(sorted(combo_set)),  # type: ignore[arg-type]
                    draw_no=draw_no,
                    draw_date=str(row.get("date", "")),
                    match_count=match_count,
                    bonus_match=bonus_match,
                    rank=rank,
                    matched_numbers=matched,
                    source_draw_no=source_draw_no,
                    checked_draw_count=len(compare_df),
                )

        return best_record

    @staticmethod
    def _rank(match_count: int, bonus_match: bool) -> Tuple[str, int]:
        if match_count == 6:
            return "1등", 5
        if match_count == 5 and bonus_match:
            return "2등", 4
        if match_count == 5:
            return "3등", 3
        if match_count == 4:
            return "4등", 2
        if match_count == 3:
            return "5등", 1
        return "낙첨", 0


