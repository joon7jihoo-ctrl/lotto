
"""
Lotto Grid AI Analyzer - PyQt6 single-file application

요청사항 반영:
- PyQt6 기반 커스텀 다크 테마 GUI
- Pandas / NumPy / Matplotlib / Seaborn 분석 및 시각화
- MVC에 가까운 구조: Model(로더/분석기/생성기), View(PyQt6 UI), Controller(흐름 제어)
- 7x7 격자 공간 매트릭스
- 8단계 레이어 분석 및 Layer 8 수학 검증 필터
- 네트워크/캐시/데모 데이터 예외 처리

주의:
- 로또는 독립 난수 추첨입니다. 본 프로그램의 "확률 점수"는 당첨 보장이 아닌
  통계적/휴리스틱 우선순위 점수입니다.
"""

from __future__ import annotations

import itertools
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd
import seaborn as sns

try:
    import requests
except ImportError:  # requests 미설치 환경에서도 앱은 데모 모드로 실행되도록 처리
    requests = None

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle


# ---------------------------------------------------------------------------
# 1. 공통 설정 / 데이터 구조
# ---------------------------------------------------------------------------

NUMBER_MIN = 1
NUMBER_MAX = 45
GRID_SIZE = 7
EMPTY_GRID_VALUE = 0
DRAW_COLUMNS = ["draw_no", "date", "n1", "n2", "n3", "n4", "n5", "n6", "bonus"]


@dataclass
class AnalysisConfig:
    """UI 설정값을 분석 레이어에 전달하기 위한 불변에 가까운 설정 객체."""

    start_draw: int = 1
    max_draw: int = 0  # 0이면 자동 최신 회차 탐색
    deadzone_window: int = 20
    top_candidate_count: int = 20
    output_limit: int = 30

    # Layer 5: 종합 가중치 매트릭스용 가중치
    recent_weight: int = 35
    missing_weight: int = 20
    square_weight: int = 25
    deadzone_weight: int = 20

    # Layer 7: 직전 회차 이월수 + 예상수 믹스 비율
    mix_previous_ratio: int = 25

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
class AnalysisResult:
    """8단계 분석 결과를 UI가 소비하기 좋은 형태로 패키징한 객체."""

    df: pd.DataFrame
    latest_draw: LottoDraw
    score_table: pd.DataFrame
    prev_square_numbers: Set[int]
    deadzone_numbers: Set[int]
    final_expected_numbers: List[int]
    candidate_pool: List[int]
    source_name: str
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


class LottoAnalysisError(RuntimeError):
    """분석 파이프라인에서 사용자에게 표시 가능한 오류."""


# ---------------------------------------------------------------------------
# 2. Layer 1 - 동적 데이터 동행: 데이터 로더 / 캐시 / 데모 폴백
# ---------------------------------------------------------------------------

class LottoDataLoader:
    """
    동행복권 회차 JSON 조회 데이터를 우선 사용하고, 로컬 CSV 캐시를 통해
    이후 실행 시 증분 업데이트합니다.

    - 네트워크 정상: 최신 회차 탐색 -> 누락 회차만 가져와 캐시에 저장
    - 네트워크 장애 + 캐시 존재: 캐시 데이터로 분석
    - 네트워크 장애 + 캐시 없음: 내장 데모 데이터로 UI/알고리즘 검증 가능
    """

    API_URL = "https://www.dhlottery.co.kr/common.do"
    FIRST_DRAW_DATE = date(2002, 12, 7)

    def __init__(self, cache_path: Optional[Path] = None, timeout: float = 5.0) -> None:
        self.cache_path = cache_path or Path.home() / ".lotto_grid_ai" / "lotto_draws_cache.csv"
        self.timeout = timeout

    def load_history(
        self,
        config: AnalysisConfig,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Tuple[pd.DataFrame, str, List[str]]:
        """전체 분석용 당첨 번호 히스토리를 로드합니다."""
        warnings: List[str] = []
        self._emit(progress, "Layer 1: 데이터 캐시 확인 중...")

        cached_df = self._load_cache()
        if not cached_df.empty:
            self._emit(progress, f"캐시 로드: {len(cached_df):,}개 회차")

        latest_no = config.max_draw if config.max_draw > 0 else 0
        network_ok = requests is not None

        if not network_ok:
            warnings.append("requests 패키지가 없어 네트워크 조회를 건너뛰고 캐시/데모 데이터로 진행했습니다.")

        if network_ok and latest_no <= 0:
            try:
                self._emit(progress, "동행복권 최신 회차 탐색 중...")
                latest_no = self.find_latest_draw_no()
                self._emit(progress, f"최신 회차 감지: {latest_no}")
            except Exception as exc:
                network_ok = False
                warnings.append(f"최신 회차 탐색 실패: {exc}")

        if latest_no <= 0 and not cached_df.empty:
            latest_no = int(cached_df["draw_no"].max())
            warnings.append("최신 회차를 네트워크로 확인하지 못해 캐시의 마지막 회차를 사용했습니다.")

        if latest_no <= 0:
            demo_df = self._make_demo_history()
            warnings.append("네트워크와 캐시를 모두 사용할 수 없어 내장 데모 데이터를 사용했습니다.")
            return demo_df, "내장 데모 데이터", warnings

        start_draw = max(NUMBER_MIN, int(config.start_draw))
        cache_slice = cached_df[
            (cached_df["draw_no"] >= start_draw) & (cached_df["draw_no"] <= latest_no)
        ].copy()

        missing_draws = self._missing_draw_numbers(cache_slice, start_draw, latest_no)

        if network_ok and missing_draws:
            self._emit(progress, f"동행복권 데이터 조회: 누락 {len(missing_draws):,}개 회차")
            fetched_rows: List[Dict[str, object]] = []
            fail_count = 0

            for idx, draw_no in enumerate(missing_draws, 1):
                try:
                    draw = self.fetch_draw(draw_no)
                    if draw is None:
                        fail_count += 1
                        continue
                    fetched_rows.append(self._draw_to_row(draw))
                except Exception:
                    fail_count += 1

                if idx % 25 == 0 or idx == len(missing_draws):
                    self._emit(progress, f"조회 진행: {idx:,}/{len(missing_draws):,}")
                    # 공개 웹 조회를 과도하게 때리지 않기 위한 짧은 양보.
                    time.sleep(0.02)

            if fail_count:
                warnings.append(f"{fail_count:,}개 회차는 조회 실패 또는 미공개 상태라 건너뛰었습니다.")

            if fetched_rows:
                fetched_df = pd.DataFrame(fetched_rows, columns=DRAW_COLUMNS)
                merged = pd.concat([cached_df, fetched_df], ignore_index=True)
                merged = self._sanitize_df(merged)
                self._save_cache(merged)
                cache_slice = merged[
                    (merged["draw_no"] >= start_draw) & (merged["draw_no"] <= latest_no)
                ].copy()
                self._emit(progress, "캐시 업데이트 완료")

        if cache_slice.empty:
            demo_df = self._make_demo_history()
            warnings.append("분석 가능한 실제 회차 데이터가 없어 내장 데모 데이터를 사용했습니다.")
            return demo_df, "내장 데모 데이터", warnings

        cache_slice = self._sanitize_df(cache_slice)
        if len(cache_slice) < 10:
            warnings.append("분석 데이터가 10회차 미만입니다. 통계 점수의 안정성이 낮을 수 있습니다.")

        source_name = "동행복권 조회 + 로컬 캐시" if network_ok else "로컬 캐시"
        return cache_slice, source_name, warnings

    def find_latest_draw_no(self) -> int:
        """
        최초 추첨일 기준 주차로 최신 회차 후보를 추정한 뒤 역방향으로 성공 응답을 찾습니다.
        동행복권 측의 회차 공개 지연이나 점검을 고려해 여유분을 둡니다.
        """
        estimated = ((date.today() - self.FIRST_DRAW_DATE).days // 7) + 1
        hint = estimated + 4
        lower_bound = max(1, hint - 40)

        for draw_no in range(hint, lower_bound - 1, -1):
            draw = self.fetch_draw(draw_no)
            if draw is not None:
                return draw.draw_no

        raise LottoAnalysisError("최근 40개 후보 회차에서 성공 응답을 찾지 못했습니다.")

    def fetch_draw(self, draw_no: int) -> Optional[LottoDraw]:
        """동행복권 회차 JSON을 단건 조회합니다."""
        if requests is None:
            return None

        params = {"method": "getLottoNumber", "drwNo": int(draw_no)}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 LottoGridAI/1.0 "
                "(educational analysis tool; contact: local-user)"
            )
        }

        response = requests.get(self.API_URL, params=params, headers=headers, timeout=self.timeout)
        response.raise_for_status()

        payload = response.json()
        if payload.get("returnValue") != "success":
            return None

        numbers = tuple(int(payload[f"drwtNo{i}"]) for i in range(1, 7))
        bonus = int(payload["bnusNo"]) if payload.get("bnusNo") else None
        draw_date = str(payload.get("drwNoDate", ""))

        if not self._is_valid_numbers(numbers):
            raise LottoAnalysisError(f"{draw_no}회차 번호 형식이 올바르지 않습니다: {numbers}")

        return LottoDraw(
            draw_no=int(payload.get("drwNo", draw_no)),
            draw_date=draw_date,
            numbers=numbers,  # type: ignore[arg-type]
            bonus=bonus,
        )

    def _load_cache(self) -> pd.DataFrame:
        if not self.cache_path.exists():
            return pd.DataFrame(columns=DRAW_COLUMNS)

        try:
            df = pd.read_csv(self.cache_path)
            return self._sanitize_df(df)
        except Exception:
            return pd.DataFrame(columns=DRAW_COLUMNS)

    def _save_cache(self, df: pd.DataFrame) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            clean = self._sanitize_df(df)
            clean.to_csv(self.cache_path, index=False, encoding="utf-8-sig")
        except Exception:
            # 캐시 저장 실패가 분석 전체 실패로 이어지지 않도록 삼킵니다.
            pass

    def _sanitize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=DRAW_COLUMNS)

        df = df.copy()
        for col in DRAW_COLUMNS:
            if col not in df.columns:
                df[col] = np.nan

        for col in ["draw_no", "n1", "n2", "n3", "n4", "n5", "n6", "bonus"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["date"] = df["date"].fillna("").astype(str)
        df = df.dropna(subset=["draw_no", "n1", "n2", "n3", "n4", "n5", "n6"])
        df[["draw_no", "n1", "n2", "n3", "n4", "n5", "n6"]] = df[
            ["draw_no", "n1", "n2", "n3", "n4", "n5", "n6"]
        ].astype(int)

        def row_valid(row: pd.Series) -> bool:
            nums = tuple(int(row[f"n{i}"]) for i in range(1, 7))
            return self._is_valid_numbers(nums)

        if not df.empty:
            df = df[df.apply(row_valid, axis=1)]

        df = df.drop_duplicates(subset=["draw_no"], keep="last")
        df = df.sort_values("draw_no").reset_index(drop=True)
        return df[DRAW_COLUMNS]

    @staticmethod
    def _is_valid_numbers(numbers: Sequence[int]) -> bool:
        return (
            len(numbers) == 6
            and len(set(numbers)) == 6
            and all(NUMBER_MIN <= int(n) <= NUMBER_MAX for n in numbers)
        )

    @staticmethod
    def _draw_to_row(draw: LottoDraw) -> Dict[str, object]:
        return {
            "draw_no": draw.draw_no,
            "date": draw.draw_date,
            "n1": draw.numbers[0],
            "n2": draw.numbers[1],
            "n3": draw.numbers[2],
            "n4": draw.numbers[3],
            "n5": draw.numbers[4],
            "n6": draw.numbers[5],
            "bonus": draw.bonus if draw.bonus is not None else np.nan,
        }

    @staticmethod
    def _missing_draw_numbers(df: pd.DataFrame, start_draw: int, latest_draw: int) -> List[int]:
        existing = set(df["draw_no"].astype(int).tolist()) if not df.empty else set()
        return [n for n in range(start_draw, latest_draw + 1) if n not in existing]

    @staticmethod
    def _emit(progress: Optional[Callable[[str], None]], message: str) -> None:
        if progress:
            progress(message)

    def _make_demo_history(self, rows: int = 180) -> pd.DataFrame:
        """
        네트워크 없는 환경에서 UI와 알고리즘을 검증하기 위한 결정론적 데모 데이터.
        실제 당첨 번호가 아니므로 source_name/warnings에 명확히 표시합니다.
        """
        rng = np.random.default_rng(645)
        start_no = 1
        start_dt = date.today() - timedelta(weeks=rows)

        records = []
        for i in range(rows):
            # 완전 무작위 대신 약한 패턴을 섞어 히트맵/레이어 효과가 눈에 보이게 만듭니다.
            base = rng.choice(np.arange(1, 46), size=6, replace=False)
            nums = sorted(int(x) for x in base)
            bonus_pool = [n for n in range(1, 46) if n not in nums]
            bonus = int(rng.choice(bonus_pool))
            records.append(
                {
                    "draw_no": start_no + i,
                    "date": str(start_dt + timedelta(weeks=i)),
                    "n1": nums[0],
                    "n2": nums[1],
                    "n3": nums[2],
                    "n4": nums[3],
                    "n5": nums[4],
                    "n6": nums[5],
                    "bonus": bonus,
                }
            )

        return pd.DataFrame(records, columns=DRAW_COLUMNS)


# ---------------------------------------------------------------------------
# 3. 7x7 격자 매핑 유틸리티
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 4. Layer 2~7 - 분석 엔진
# ---------------------------------------------------------------------------

class LottoAnalyzer:
    """로또 번호 히스토리에서 8단계 중 Layer 2~7의 점수/후보군을 산출합니다."""

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
        latest_row = clean_df.iloc[-1]
        latest_numbers = self._row_numbers(latest_row)
        latest_draw = LottoDraw(
            draw_no=int(latest_row["draw_no"]),
            draw_date=str(latest_row.get("date", "")),
            numbers=latest_numbers,  # type: ignore[arg-type]
            bonus=int(latest_row["bonus"]) if pd.notna(latest_row.get("bonus", np.nan)) else None,
        )

        # Layer 2: 시계열 빈도 및 장기 미출수
        freq_score, freq_counts = self._layer2_frequency_score(clean_df)
        missing_score, missing_gap = self._layer2_missing_score(clean_df)

        # Layer 3: 직전사각수 알고리즘
        square_score, prev_square_numbers, square_hit_count = self._layer3_previous_square(latest_numbers)

        # Layer 4: 완전사각/데드존 추적
        deadzone_score, deadzone_numbers, deadzone_recent_counts = self._layer4_deadzone(
            clean_df, config.deadzone_window
        )

        # Layer 5: 종합 가중치 매트릭스
        composite_score = self._layer5_composite(
            freq_score=freq_score,
            missing_score=missing_score,
            square_score=square_score,
            deadzone_score=deadzone_score,
            config=config,
        )

        numbers = np.arange(1, NUMBER_MAX + 1)
        latest_set = set(latest_numbers)

        score_table = pd.DataFrame(
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

        # Layer 6: 최적 예상수 필터 - 종합 점수 상위 N개로 압축
        top_n = int(np.clip(config.top_candidate_count, 6, NUMBER_MAX))
        final_expected_numbers = score_table.head(top_n)["number"].astype(int).tolist()

        # Layer 7: 이전당첨 + 예상수 믹서
        candidate_pool = self._layer7_mix_previous_and_expected(
            latest_numbers=latest_numbers,
            final_expected_numbers=final_expected_numbers,
            score_table=score_table,
            config=config,
        )

        return AnalysisResult(
            df=clean_df,
            latest_draw=latest_draw,
            score_table=score_table,
            prev_square_numbers=prev_square_numbers,
            deadzone_numbers=deadzone_numbers,
            final_expected_numbers=final_expected_numbers,
            candidate_pool=candidate_pool,
            source_name=source_name,
            warnings=warnings or [],
        )

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


# ---------------------------------------------------------------------------
# 5. Layer 8 - 수학적 검증 필터 및 조합 생성
# ---------------------------------------------------------------------------

class CombinationGenerator:
    """Layer 8 필터를 만족하는 6개 번호 조합을 생성하고 랭킹합니다."""

    MAX_POOL_FOR_FULL_SEARCH = 28

    def generate(
        self,
        analysis: AnalysisResult,
        config: AnalysisConfig,
    ) -> Tuple[List[CombinationRecord], List[str]]:
        warnings: List[str] = []

        pool = list(dict.fromkeys(int(n) for n in analysis.candidate_pool))
        if len(pool) < 6:
            raise LottoAnalysisError("후보 번호가 6개 미만이라 조합을 생성할 수 없습니다.")

        if len(pool) > self.MAX_POOL_FOR_FULL_SEARCH:
            warnings.append(
                f"조합 폭증 방지를 위해 후보군 {len(pool)}개 중 상위 "
                f"{self.MAX_POOL_FOR_FULL_SEARCH}개만 사용했습니다."
            )
            pool = pool[: self.MAX_POOL_FOR_FULL_SEARCH]

        score_map = {
            int(row["number"]): float(row["score"])
            for _, row in analysis.score_table.iterrows()
        }

        latest_set = set(int(n) for n in analysis.latest_draw.numbers)

        records = self._search(pool, score_map, latest_set, config, enforce_carry=True)

        if not records:
            warnings.append("이월수 믹스 조건까지 만족하는 조합이 없어 믹스 조건만 완화해 재탐색했습니다.")
            records = self._search(pool, score_map, latest_set, config, enforce_carry=False)

        records.sort(
            key=lambda r: (
                r.score,
                r.ac_value,
                -abs(r.total - ((config.sum_min + config.sum_max) / 2.0)),
            ),
            reverse=True,
        )

        return records[: max(1, config.output_limit)], warnings

    def _search(
        self,
        pool: Sequence[int],
        score_map: Dict[int, float],
        latest_set: Set[int],
        config: AnalysisConfig,
        enforce_carry: bool,
    ) -> List[CombinationRecord]:
        target_carry = int(round(6 * np.clip(config.mix_previous_ratio, 0, 100) / 100.0))

        if config.mix_previous_ratio <= 5:
            carry_min, carry_max = 0, 1
        elif config.mix_previous_ratio >= 95:
            carry_min, carry_max = 5, 6
        else:
            carry_min, carry_max = max(0, target_carry - 1), min(6, target_carry + 1)

        records: List[CombinationRecord] = []

        for combo in itertools.combinations(sorted(pool), 6):
            total = sum(combo)
            if total < config.sum_min or total > config.sum_max:
                continue

            odd_count = sum(1 for n in combo if n % 2 == 1)
            if odd_count < config.odd_min or odd_count > config.odd_max:
                continue

            high_count = sum(1 for n in combo if n >= 23)
            if high_count < config.high_min or high_count > config.high_max:
                continue

            ac = self.ac_value(combo)
            if ac < config.min_ac:
                continue

            carry_count = sum(1 for n in combo if n in latest_set)
            if enforce_carry and not (carry_min <= carry_count <= carry_max):
                continue

            # 조합 랭킹 점수:
            # - 번호별 종합 점수 합산
            # - AC값이 높을수록 약간 가산
            # - 총합 범위 중앙에 가까울수록 약간 가산
            score_sum = sum(score_map.get(n, 0.0) for n in combo)
            ideal_sum = (config.sum_min + config.sum_max) / 2.0
            balance_bonus = max(0.0, 20.0 - abs(total - ideal_sum)) * 0.35
            ac_bonus = ac * 1.3
            carry_bonus = carry_count * 0.7
            rank_score = score_sum + balance_bonus + ac_bonus + carry_bonus

            records.append(
                CombinationRecord(
                    numbers=tuple(combo),  # type: ignore[arg-type]
                    total=total,
                    odd_count=odd_count,
                    high_count=high_count,
                    ac_value=ac,
                    carry_count=carry_count,
                    score=rank_score,
                )
            )

        return records

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


# ---------------------------------------------------------------------------
# 6. View - PyQt6 UI 위젯
# ---------------------------------------------------------------------------

class SliderSpinBox(QWidget):
    """QSlider와 QSpinBox를 양방향으로 묶은 재사용 UI 컴포넌트."""

    valueChanged = pyqtSignal(int)

    def __init__(
        self,
        title: str,
        minimum: int,
        maximum: int,
        value: int,
        suffix: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.title_label = QLabel(title)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.spin = QSpinBox()

        self.slider.setRange(minimum, maximum)
        self.spin.setRange(minimum, maximum)
        self.spin.setSuffix(suffix)
        self.slider.setValue(value)
        self.spin.setValue(value)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(max(1, (maximum - minimum) // 5))

        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        self.spin.valueChanged.connect(self.valueChanged.emit)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(self.title_label, 0, 0, 1, 2)
        layout.addWidget(self.slider, 1, 0)
        layout.addWidget(self.spin, 1, 1)

    def value(self) -> int:
        return int(self.spin.value())

    def setValue(self, value: int) -> None:
        self.spin.setValue(value)


class HeatmapCanvas(FigureCanvas):
    """Matplotlib 7x7 격자 히트맵 + 레이어 오버레이 캔버스."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        sns.set_theme(context="notebook", style="darkgrid")
        self.figure = Figure(figsize=(6.4, 6.4), dpi=110, facecolor="#0b1020")
        self.ax = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)
        self.render_empty()

    def render_empty(self) -> None:
        self.ax.clear()
        self.ax.set_facecolor("#0b1020")
        self.ax.text(
            0.5,
            0.5,
            "데이터를 로드하면\n7x7 레이어 히트맵이 표시됩니다",
            ha="center",
            va="center",
            color="#cbd5e1",
            fontsize=13,
            transform=self.ax.transAxes,
        )
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.figure.tight_layout()
        self.draw_idle()

    def render(self, result: AnalysisResult) -> None:
        self.ax.clear()
        self.ax.set_facecolor("#0b1020")

        score_map = {
            int(row["number"]): float(row["score"])
            for _, row in result.score_table.iterrows()
        }
        score_grid = GridMapper.numbers_to_grid(score_map, fill_value=np.nan)

        cmap = sns.color_palette("mako", as_cmap=True)
        masked = np.ma.masked_invalid(score_grid)
        image = self.ax.imshow(masked, cmap=cmap, vmin=0, vmax=100, interpolation="nearest")

        # 빈칸(46~49)을 명시적으로 표시
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                number = GridMapper.pos_to_number(row, col)
                if number is None:
                    self.ax.add_patch(
                        Rectangle(
                            (col - 0.5, row - 0.5),
                            1,
                            1,
                            facecolor="#111827",
                            edgecolor="#334155",
                            linewidth=1.0,
                            hatch="///",
                            alpha=0.7,
                        )
                    )

        # 기본 격자선
        for edge in np.arange(-0.5, GRID_SIZE, 1):
            self.ax.axhline(edge, color="#334155", linewidth=0.8, alpha=0.85)
            self.ax.axvline(edge, color="#334155", linewidth=0.8, alpha=0.85)

        # Layer 4: 완전사각/데드존 - 차가운 청색 반투명 면
        for number in result.deadzone_numbers:
            row, col = GridMapper.number_to_pos(number)
            self.ax.add_patch(
                Rectangle(
                    (col - 0.5, row - 0.5),
                    1,
                    1,
                    facecolor="#38bdf8",
                    edgecolor="#7dd3fc",
                    linewidth=1.5,
                    alpha=0.18,
                )
            )

        # Layer 3: 직전사각수 - 노란색 테두리
        for number in result.prev_square_numbers:
            row, col = GridMapper.number_to_pos(number)
            self.ax.add_patch(
                Rectangle(
                    (col - 0.5, row - 0.5),
                    1,
                    1,
                    facecolor="#f59e0b",
                    edgecolor="#fbbf24",
                    linewidth=2.0,
                    alpha=0.20,
                )
            )

        # Layer 6: 최종 예상수 - 녹색 두꺼운 테두리
        for number in result.final_expected_numbers:
            row, col = GridMapper.number_to_pos(number)
            self.ax.add_patch(
                Rectangle(
                    (col - 0.5, row - 0.5),
                    1,
                    1,
                    fill=False,
                    edgecolor="#22c55e",
                    linewidth=2.6,
                    alpha=0.95,
                )
            )

        latest_set = set(result.latest_draw.numbers)

        # 번호 라벨
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                number = GridMapper.pos_to_number(row, col)
                if number is None:
                    continue

                score = score_map.get(number, 0.0)
                color = "#ffffff" if score >= 50 else "#e2e8f0"
                weight = "bold" if number in latest_set else "normal"

                label = f"{number}\n{score:.0f}"
                self.ax.text(
                    col,
                    row,
                    label,
                    ha="center",
                    va="center",
                    color=color,
                    fontsize=9.5,
                    fontweight=weight,
                )

        self.ax.set_xticks(range(GRID_SIZE))
        self.ax.set_yticks(range(GRID_SIZE))
        self.ax.set_xticklabels([str(i + 1) for i in range(GRID_SIZE)], color="#94a3b8")
        self.ax.set_yticklabels([str(i + 1) for i in range(GRID_SIZE)], color="#94a3b8")
        self.ax.set_title(
            "7x7 Grid Layered Heatmap  |  점수·직전사각·데드존·예상수",
            color="#f8fafc",
            fontsize=12,
            pad=12,
        )

        cbar = self.figure.colorbar(image, ax=self.ax, fraction=0.046, pad=0.04)
        cbar.ax.tick_params(colors="#cbd5e1")
        cbar.outline.set_edgecolor("#334155")
        cbar.set_label("Composite Score", color="#cbd5e1")

        self.ax.set_xlim(-0.5, GRID_SIZE - 0.5)
        self.ax.set_ylim(GRID_SIZE - 0.5, -0.5)
        self.figure.tight_layout()
        self.draw_idle()


class MainWindow(QMainWindow):
    """View: UI 구성과 표시만 담당합니다."""

    analysis_requested = pyqtSignal()
    generate_requested = pyqtSignal()
    settings_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DDoS 공격 방어")
        self.resize(1480, 920)
        self._build_actions()
        self._build_ui()
        self._connect_setting_signals()
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("준비 완료")

    def _build_actions(self) -> None:
        about_action = QAction("정보", self)
        about_action.triggered.connect(self._show_about)

        menubar = self.menuBar()
        help_menu = menubar.addMenu("도움말")
        help_menu.addAction(about_action)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        controls = self._build_controls_panel()
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(controls)
        left_scroll.setMinimumWidth(330)
        left_scroll.setMaximumWidth(430)

        center = self._build_center_panel()
        right = self._build_right_panel()

        splitter.addWidget(left_scroll)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setSizes([360, 720, 420])

        root.addWidget(splitter)
        self.setCentralWidget(central)

    def _build_controls_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        title = QLabel("Lotto Grid AI Analyzer")
        title.setObjectName("TitleLabel")
        subtitle = QLabel("8-Layer Spatial Matrix Engine")
        subtitle.setObjectName("SubtitleLabel")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        data_group = QGroupBox("Layer 1 · 동적 데이터 로드")
        data_layout = QGridLayout(data_group)

        self.start_draw_spin = QSpinBox()
        self.start_draw_spin.setRange(1, 3000)
        self.start_draw_spin.setValue(1)

        self.max_draw_spin = QSpinBox()
        self.max_draw_spin.setRange(0, 3000)
        self.max_draw_spin.setValue(0)
        self.max_draw_spin.setSpecialValueText("자동")

        data_layout.addWidget(QLabel("시작 회차"), 0, 0)
        data_layout.addWidget(self.start_draw_spin, 0, 1)
        data_layout.addWidget(QLabel("최대 회차"), 1, 0)
        data_layout.addWidget(self.max_draw_spin, 1, 1)

        self.load_button = QPushButton("데이터 로드 + 8단계 분석")
        self.load_button.setObjectName("PrimaryButton")
        self.load_button.clicked.connect(self.analysis_requested.emit)
        data_layout.addWidget(self.load_button, 2, 0, 1, 2)

        layout.addWidget(data_group)

        weight_group = QGroupBox("Layer 2~5 · 예상수 가중치")
        weight_layout = QVBoxLayout(weight_group)

        self.recent_weight = SliderSpinBox("시계열 빈도 가중치", 0, 100, 35)
        self.missing_weight = SliderSpinBox("장기 미출수 가중치", 0, 100, 20)
        self.square_weight = SliderSpinBox("직전사각수 가중치", 0, 100, 25)
        self.deadzone_weight = SliderSpinBox("완전사각/데드존 가중치", 0, 100, 20)

        weight_layout.addWidget(self.recent_weight)
        weight_layout.addWidget(self.missing_weight)
        weight_layout.addWidget(self.square_weight)
        weight_layout.addWidget(self.deadzone_weight)

        layout.addWidget(weight_group)

        candidate_group = QGroupBox("Layer 6~8 · 후보/검증 설정")
        candidate_layout = QGridLayout(candidate_group)

        self.deadzone_window_spin = QSpinBox()
        self.deadzone_window_spin.setRange(1, 200)
        self.deadzone_window_spin.setValue(20)
        self.deadzone_window_spin.setSuffix(" 회")

        self.top_candidate_spin = QSpinBox()
        self.top_candidate_spin.setRange(6, 45)
        self.top_candidate_spin.setValue(20)
        self.top_candidate_spin.setSuffix(" 개")

        self.output_limit_spin = QSpinBox()
        self.output_limit_spin.setRange(1, 300)
        self.output_limit_spin.setValue(30)
        self.output_limit_spin.setSuffix(" 조합")

        self.mix_ratio = SliderSpinBox("이전당첨 믹스 비율", 0, 100, 25, "%")

        candidate_layout.addWidget(QLabel("데드존 추적 N"), 0, 0)
        candidate_layout.addWidget(self.deadzone_window_spin, 0, 1)
        candidate_layout.addWidget(QLabel("핵심 예상수 N"), 1, 0)
        candidate_layout.addWidget(self.top_candidate_spin, 1, 1)
        candidate_layout.addWidget(QLabel("출력 조합 수"), 2, 0)
        candidate_layout.addWidget(self.output_limit_spin, 2, 1)
        candidate_layout.addWidget(self.mix_ratio, 3, 0, 1, 2)

        self.generate_button = QPushButton("최적 번호 조합 생성")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.clicked.connect(self.generate_requested.emit)
        candidate_layout.addWidget(self.generate_button, 4, 0, 1, 2)

        layout.addWidget(candidate_group)

        filter_group = QGroupBox("Layer 8 · 고정 수학 필터")
        filter_layout = QVBoxLayout(filter_group)
        filter_text = QLabel(
            "· 총합: 100~170\n"
            "· 홀짝: 홀수 2~4개\n"
            "· 고저: 고번호(23~45) 2~4개\n"
            "· AC값: 7 이상"
        )
        filter_text.setObjectName("HintLabel")
        filter_layout.addWidget(filter_text)
        layout.addWidget(filter_group)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(140)
        self.log_box.setObjectName("LogBox")
        layout.addWidget(QLabel("진행 로그"))
        layout.addWidget(self.log_box)

        layout.addStretch(1)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.summary_card = QLabel("데이터를 로드해 주세요.")
        self.summary_card.setObjectName("SummaryCard")
        self.summary_card.setWordWrap(True)

        self.heatmap = HeatmapCanvas()

        legend = QLabel(
            "Legend  |  노란색: 직전사각수  ·  파란색: 완전사각/데드존  ·  녹색 테두리: 최종 예상수  ·  굵은 번호: 직전 회차"
        )
        legend.setObjectName("HintLabel")
        legend.setWordWrap(True)

        layout.addWidget(self.summary_card)
        layout.addWidget(self.heatmap, 1)
        layout.addWidget(legend)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        table_title = QLabel("번호별 종합 점수")
        table_title.setObjectName("PanelTitle")
        layout.addWidget(table_title)

        self.score_table = QTableWidget(0, 7)
        self.score_table.setHorizontalHeaderLabels(["번호", "점수", "최근", "미출", "사각", "데드존", "이월"])
        self.score_table.verticalHeader().setVisible(False)
        self.score_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.score_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.score_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.score_table.setAlternatingRowColors(True)
        layout.addWidget(self.score_table, 1)

        combos_title = QLabel("Layer 8 생존 최종 조합")
        combos_title.setObjectName("PanelTitle")
        layout.addWidget(combos_title)

        self.combo_output = QTextEdit()
        self.combo_output.setReadOnly(True)
        self.combo_output.setFont(QFont("Consolas", 10))
        self.combo_output.setObjectName("ComboOutput")
        layout.addWidget(self.combo_output, 1)

        return panel

    def _connect_setting_signals(self) -> None:
        widgets = [
            self.start_draw_spin,
            self.max_draw_spin,
            self.deadzone_window_spin,
            self.top_candidate_spin,
            self.output_limit_spin,
            self.recent_weight,
            self.missing_weight,
            self.square_weight,
            self.deadzone_weight,
            self.mix_ratio,
        ]

        for widget in widgets:
            if isinstance(widget, SliderSpinBox):
                widget.valueChanged.connect(self.settings_changed.emit)
            else:
                widget.valueChanged.connect(self.settings_changed.emit)

    def get_config(self) -> AnalysisConfig:
        return AnalysisConfig(
            start_draw=int(self.start_draw_spin.value()),
            max_draw=int(self.max_draw_spin.value()),
            deadzone_window=int(self.deadzone_window_spin.value()),
            top_candidate_count=int(self.top_candidate_spin.value()),
            output_limit=int(self.output_limit_spin.value()),
            recent_weight=self.recent_weight.value(),
            missing_weight=self.missing_weight.value(),
            square_weight=self.square_weight.value(),
            deadzone_weight=self.deadzone_weight.value(),
            mix_previous_ratio=self.mix_ratio.value(),
        )

    def set_busy(self, busy: bool) -> None:
        self.load_button.setEnabled(not busy)
        self.generate_button.setEnabled(not busy)
        if busy:
            self.statusBar().showMessage("분석 실행 중...")
            self.load_button.setText("분석 중...")
        else:
            self.statusBar().showMessage("준비 완료")
            self.load_button.setText("데이터 로드 + 8단계 분석")

    def clear_log(self) -> None:
        self.log_box.clear()

    def append_log(self, message: str) -> None:
        self.log_box.append(f"• {message}")
        self.log_box.moveCursor(self.log_box.textCursor().MoveOperation.End)

    def show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def show_analysis(self, result: AnalysisResult) -> None:
        latest = result.latest_draw
        warning_text = ""
        if result.warnings:
            warning_text = "\n주의: " + " / ".join(result.warnings[:3])

        self.summary_card.setText(
            f"데이터 소스: {result.source_name}\n"
            f"분석 회차 수: {len(result.df):,}회 · 최신 회차: {latest.draw_no}회 ({latest.draw_date})\n"
            f"직전 당첨: {format_numbers(latest.numbers)} · 보너스: {latest.bonus if latest.bonus is not None else '-'}\n"
            f"핵심 예상수: {format_numbers(result.final_expected_numbers)}\n"
            f"조합 후보군: {format_numbers(result.candidate_pool)}"
            f"{warning_text}"
        )

        self.heatmap.render(result)
        self._fill_score_table(result)
        self.combo_output.setPlainText("상단의 '최적 번호 조합 생성' 버튼을 누르면 Layer 8 생존 조합이 표시됩니다.")

    def show_combinations(self, records: List[CombinationRecord], warnings: Optional[List[str]] = None) -> None:
        if not records:
            self.combo_output.setPlainText("조건을 만족하는 조합을 찾지 못했습니다. 후보수 N 또는 믹스 비율을 조정해 보세요.")
            return

        lines: List[str] = []
        if warnings:
            for warning in warnings:
                lines.append(f"[주의] {warning}")
            lines.append("")

        lines.append("순위 | 번호 조합                 | 총합 | 홀 | 고 | AC | 이월 | 점수")
        lines.append("-" * 78)

        for idx, record in enumerate(records, 1):
            combo = " ".join(f"{n:02d}" for n in record.numbers)
            lines.append(
                f"{idx:>3} | {combo:<23} | "
                f"{record.total:>3} | {record.odd_count:>1} | {record.high_count:>1} | "
                f"{record.ac_value:>2} | {record.carry_count:>2} | {record.score:>7.2f}"
            )

        self.combo_output.setPlainText("\n".join(lines))

    def _fill_score_table(self, result: AnalysisResult) -> None:
        table = result.score_table.copy().reset_index(drop=True)
        self.score_table.setRowCount(len(table))

        for row_idx, row in table.iterrows():
            values = [
                int(row["number"]),
                f"{float(row['score']):.1f}",
                int(row["freq_recent_count"]),
                int(row["missing_gap"]),
                int(row["square_hit_count"]),
                "Y" if bool(row["is_deadzone"]) else "",
                "Y" if bool(row["is_latest"]) else "",
            ]

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.score_table.setItem(row_idx, col_idx, item)

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "정보",
            "Lotto Grid AI Analyzer\n\n"
            "7x7 격자 공간 분석과 8단계 레이어 휴리스틱을 적용한 PyQt6 예제입니다.\n"
            "로또 추첨은 독립 무작위 사건이며, 본 도구는 당첨을 보장하지 않습니다.",
        )


# ---------------------------------------------------------------------------
# 7. Controller - UI 이벤트와 Model 실행 흐름 제어
# ---------------------------------------------------------------------------

class AnalysisTaskWorker(QObject):
    """네트워크/캐시 데이터 로드와 분석을 UI 스레드 밖에서 수행."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, config: AnalysisConfig) -> None:
        super().__init__()
        self.config = config

    def run(self) -> None:
        try:
            loader = LottoDataLoader()
            analyzer = LottoAnalyzer()

            df, source_name, warnings = loader.load_history(self.config, self.progress.emit)
            self.progress.emit("Layer 2~7: 가중치 매트릭스 분석 중...")
            result = analyzer.analyze(df, self.config, source_name, warnings)
            self.progress.emit("분석 완료")
            self.finished.emit(result)

        except Exception as exc:
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.failed.emit(detail)


class LottoController(QObject):
    """Controller: View 시그널을 받아 Model을 실행하고 결과를 다시 View에 반영."""

    def __init__(self, view: MainWindow) -> None:
        super().__init__()
        self.view = view
        self.analyzer = LottoAnalyzer()
        self.generator = CombinationGenerator()

        self.current_result: Optional[AnalysisResult] = None
        self.current_source_name: str = ""
        self.current_warnings: List[str] = []

        self.thread: Optional[QThread] = None
        self.worker: Optional[AnalysisTaskWorker] = None

        self.debounce_timer = QTimer(self)
        self.debounce_timer.setInterval(250)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self._reanalyze_current_data)

        self.view.analysis_requested.connect(self.start_analysis)
        self.view.generate_requested.connect(self.generate_combinations)
        self.view.settings_changed.connect(self._schedule_reanalysis)

    def start_analysis(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            return

        config = self.view.get_config()
        self.view.set_busy(True)
        self.view.clear_log()
        self.view.append_log("분석 작업 시작")

        self.thread = QThread(self)
        self.worker = AnalysisTaskWorker(config)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.view.append_log)
        self.worker.finished.connect(self._on_analysis_finished)
        self.worker.failed.connect(self._on_analysis_failed)

        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup_thread)

        self.thread.start()

    def _on_analysis_finished(self, result: AnalysisResult) -> None:
        self.current_result = result
        self.current_source_name = result.source_name
        self.current_warnings = result.warnings
        self.view.show_analysis(result)
        self.view.set_busy(False)

    def _on_analysis_failed(self, message: str) -> None:
        self.view.set_busy(False)
        self.view.append_log(f"실패: {message}")
        self.view.show_error("분석 실패", message)

    def _cleanup_thread(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        if self.thread is not None:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None

    def _schedule_reanalysis(self) -> None:
        if self.current_result is None:
            return
        self.debounce_timer.start()

    def _reanalyze_current_data(self) -> None:
        """
        가중치/후보수/믹스 설정 변경 시 네트워크 재조회 없이 현재 DataFrame으로 빠르게 재분석합니다.
        """
        if self.current_result is None:
            return

        try:
            config = self.view.get_config()
            refreshed = self.analyzer.analyze(
                self.current_result.df,
                config,
                self.current_source_name or self.current_result.source_name,
                self.current_warnings,
            )
            self.current_result = refreshed
            self.view.show_analysis(refreshed)
            self.view.statusBar().showMessage("설정 변경 반영 완료")
        except Exception as exc:
            self.view.append_log(f"설정 반영 실패: {exc}")

    def generate_combinations(self) -> None:
        if self.current_result is None:
            self.view.show_error("데이터 없음", "먼저 '데이터 로드 + 8단계 분석'을 실행해 주세요.")
            return

        try:
            config = self.view.get_config()
            # 설정 변경 후 바로 생성할 때 최신 설정이 반영되도록 한 번 더 동기 재분석.
            refreshed = self.analyzer.analyze(
                self.current_result.df,
                config,
                self.current_source_name or self.current_result.source_name,
                self.current_warnings,
            )
            self.current_result = refreshed
            self.view.show_analysis(refreshed)

            self.view.append_log("Layer 8: 수학 검증 필터 기반 조합 생성 중...")
            records, warnings = self.generator.generate(refreshed, config)
            self.view.show_combinations(records, warnings)
            self.view.append_log(f"최종 생존 조합 {len(records):,}개 출력")
        except Exception as exc:
            self.view.show_error("조합 생성 실패", str(exc))


# ---------------------------------------------------------------------------
# 8. 스타일 / 유틸리티 / 엔트리포인트
# ---------------------------------------------------------------------------

def format_numbers(numbers: Iterable[int]) -> str:
    return " ".join(f"{int(n):02d}" for n in numbers)


def apply_dark_theme(app: QApplication) -> None:
    app.setStyleSheet(
        """
        * {
            font-family: "Segoe UI", "Pretendard", "Apple SD Gothic Neo", sans-serif;
            font-size: 13px;
        }

        QMainWindow, QWidget {
            background: #0b1020;
            color: #e5e7eb;
        }

        QMenuBar {
            background: #0f172a;
            color: #e5e7eb;
            border-bottom: 1px solid #1e293b;
        }

        QMenuBar::item:selected, QMenu::item:selected {
            background: #1d4ed8;
        }

        QMenu {
            background: #111827;
            color: #e5e7eb;
            border: 1px solid #334155;
        }

        QLabel#TitleLabel {
            color: #f8fafc;
            font-size: 24px;
            font-weight: 800;
            padding: 4px 0 0 0;
        }

        QLabel#SubtitleLabel {
            color: #38bdf8;
            font-size: 13px;
            font-weight: 600;
            padding-bottom: 8px;
        }

        QLabel#PanelTitle {
            color: #f8fafc;
            font-size: 16px;
            font-weight: 700;
            padding: 6px 0;
        }

        QLabel#SummaryCard {
            background: #111827;
            color: #e5e7eb;
            border: 1px solid #334155;
            border-radius: 14px;
            padding: 14px;
            line-height: 150%;
        }

        QLabel#HintLabel {
            color: #94a3b8;
            padding: 4px;
        }

        QGroupBox {
            color: #f8fafc;
            font-weight: 700;
            border: 1px solid #263449;
            border-radius: 14px;
            margin-top: 12px;
            padding: 12px;
            background: #0f172a;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            padding: 0 6px;
            color: #93c5fd;
        }

        QScrollArea {
            border: none;
        }

        QSpinBox {
            background: #111827;
            color: #f8fafc;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 6px;
            min-height: 24px;
        }

        QSpinBox:focus {
            border: 1px solid #38bdf8;
        }

        QSlider::groove:horizontal {
            height: 8px;
            background: #1e293b;
            border-radius: 4px;
        }

        QSlider::handle:horizontal {
            background: #38bdf8;
            width: 18px;
            margin: -6px 0;
            border-radius: 9px;
            border: 1px solid #bae6fd;
        }

        QSlider::sub-page:horizontal {
            background: #2563eb;
            border-radius: 4px;
        }

        QPushButton {
            background: #1f2937;
            color: #e5e7eb;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 10px 12px;
            font-weight: 700;
        }

        QPushButton:hover {
            background: #273449;
            border: 1px solid #38bdf8;
        }

        QPushButton:pressed {
            background: #0f172a;
        }

        QPushButton:disabled {
            background: #111827;
            color: #64748b;
            border: 1px solid #1e293b;
        }

        QPushButton#PrimaryButton {
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 #2563eb,
                stop:1 #0891b2
            );
            color: white;
            border: none;
        }

        QPushButton#PrimaryButton:hover {
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 #1d4ed8,
                stop:1 #0e7490
            );
        }

        QTextEdit, QTableWidget {
            background: #0f172a;
            color: #e5e7eb;
            border: 1px solid #263449;
            border-radius: 12px;
            padding: 8px;
            selection-background-color: #2563eb;
            selection-color: white;
        }

        QTextEdit#LogBox {
            color: #cbd5e1;
        }

        QTextEdit#ComboOutput {
            color: #dcfce7;
            background: #07111f;
        }

        QHeaderView::section {
            background: #172033;
            color: #e5e7eb;
            border: none;
            border-right: 1px solid #263449;
            padding: 7px;
            font-weight: 700;
        }

        QTableWidget::item {
            padding: 6px;
            border-bottom: 1px solid #111827;
        }

        QTableWidget::item:alternate {
            background: #111827;
        }

        QSplitter::handle {
            background: #1e293b;
        }

        QStatusBar {
            background: #0f172a;
            color: #94a3b8;
            border-top: 1px solid #1e293b;
        }
        """
    )


def main() -> int:
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    window = MainWindow()
    _controller = LottoController(window)  # noqa: F841 - Qt 객체 생명주기 유지를 위해 참조 보존
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
