"""Core constants, configuration, and data transfer objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple

import pandas as pd

NUMBER_MIN = 1
NUMBER_MAX = 45
GRID_SIZE = 7
EMPTY_GRID_VALUE = 0
DRAW_COLUMNS = ["draw_no", "date", "n1", "n2", "n3", "n4", "n5", "n6", "bonus"]
APP_DIR = Path(__file__).resolve().parents[1] if "__file__" in globals() else Path.cwd()
EXCEL_HISTORY_FILE = APP_DIR / "lotto_history.xlsx"
SQLITE_DB_FILE = APP_DIR / "lotto_history.db"


@dataclass
class AnalysisConfig:
    """UI 설정값을 분석 레이어에 전달하기 위한 불변에 가까운 설정 객체."""

    start_draw: int = 1
    max_draw: int = 0  # 0이면 자동 최신 회차 탐색
    deadzone_window: int = 20
    top_candidate_count: int = 20
    output_limit: int = 30

    # Layer 5: 종합 가중치 매트릭스용 가중치
    recent_weight: int = 55
    missing_weight: int = 25
    square_weight: int = 0
    deadzone_weight: int = 5

    # Layer 7: 직전 회차 이월수 + 예상수 믹스 비율
    mix_previous_ratio: int = 10

    # Layer 8~10: 조합 관리 / 검증 설정
    max_overlap: int = 3
    max_popularity_risk: int = 3
    backtest_rounds: int = 80
    backtest_train_window: int = 120

    # Layer 8: 수학 검증 필터
    sum_min: int = 100
    sum_max: int = 170
    min_ac: int = 7
    odd_min: int = 2
    odd_max: int = 4
    high_min: int = 2
    high_max: int = 4


@dataclass
class LottoDraw:
    """한 회차의 당첨 번호 데이터."""

    draw_no: int
    draw_date: str
    numbers: Tuple[int, int, int, int, int, int]
    bonus: Optional[int] = None


@dataclass
class BacktestSummary:
    """후보군 레이어가 무작위 선택 대비 어떤지 요약하는 롤링 백테스트 결과."""

    rounds: int = 0
    train_window: int = 0
    candidate_count: int = 0
    avg_hits: float = 0.0
    random_avg_hits: float = 0.0
    hit3_rate: float = 0.0
    random_hit3_rate: float = 0.0
    hit4_rate: float = 0.0
    random_hit4_rate: float = 0.0
    best_hit_count: int = 0
    last_hit_count: int = 0


@dataclass
class AnalysisResult:
    """분석/백테스트/후보군 결과를 UI가 소비하기 좋은 형태로 패키징한 객체."""

    df: pd.DataFrame
    latest_draw: LottoDraw
    score_table: pd.DataFrame
    prev_square_numbers: Set[int]
    deadzone_numbers: Set[int]
    final_expected_numbers: List[int]
    candidate_pool: List[int]
    source_name: str
    backtest_summary: BacktestSummary = field(default_factory=BacktestSummary)
    warnings: List[str] = field(default_factory=list)


@dataclass
class CombinationRecord:
    """최종 조합 후보와 검증 메트릭."""

    numbers: Tuple[int, int, int, int, int, int]
    total: int
    odd_count: int
    high_count: int
    ac_value: int
    carry_count: int
    score: float
    source_draw_no: Optional[int] = None
    pattern_risk: int = 0
    pattern_notes: str = ""


@dataclass
class WinningCheckRecord:
    """생성된 조합을 실제 회차 이력과 대조한 최선의 당첨 결과."""

    numbers: Tuple[int, int, int, int, int, int]
    draw_no: Optional[int]
    draw_date: str
    match_count: int
    bonus_match: bool
    rank: str
    matched_numbers: Tuple[int, ...]
    source_draw_no: Optional[int] = None
    checked_draw_count: int = 0


class LottoAnalysisError(RuntimeError):
    """분석 파이프라인에서 사용자에게 표시 가능한 오류."""
