"""SQLite persistence and lotto history loading/updating."""

from __future__ import annotations

import sqlite3
import time
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:  # requests 미설치 환경에서도 앱은 데모 모드로 실행되도록 처리
    requests = None

from .models import (
    DRAW_COLUMNS,
    EXCEL_HISTORY_FILE,
    NUMBER_MAX,
    NUMBER_MIN,
    SQLITE_DB_FILE,
    AnalysisConfig,
    CombinationRecord,
    LottoAnalysisError,
    LottoDraw,
)
from .utils import format_numbers


class LottoDatabase:
    """로또 이력과 생성 조합을 저장하는 SQLite 저장소."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or SQLITE_DB_FILE

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._create_draws_table(conn)
            self._create_generated_table(conn)
            self._migrate_generated_table(conn)

    @staticmethod
    def _create_draws_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lotto_draws (
                draw_no INTEGER PRIMARY KEY,
                date TEXT NOT NULL DEFAULT '',
                n1 INTEGER NOT NULL,
                n2 INTEGER NOT NULL,
                n3 INTEGER NOT NULL,
                n4 INTEGER NOT NULL,
                n5 INTEGER NOT NULL,
                n6 INTEGER NOT NULL,
                bonus INTEGER,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    @staticmethod
    def _create_generated_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generated_combinations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_at TEXT NOT NULL,
                source_draw_no INTEGER,
                numbers_text TEXT NOT NULL,
                n1 INTEGER NOT NULL,
                n2 INTEGER NOT NULL,
                n3 INTEGER NOT NULL,
                n4 INTEGER NOT NULL,
                n5 INTEGER NOT NULL,
                n6 INTEGER NOT NULL,
                total INTEGER NOT NULL,
                odd_count INTEGER NOT NULL,
                high_count INTEGER NOT NULL,
                ac_value INTEGER NOT NULL,
                carry_count INTEGER NOT NULL,
                score REAL NOT NULL,
                pattern_risk INTEGER NOT NULL DEFAULT 0,
                pattern_notes TEXT NOT NULL DEFAULT ''
            )
            """
        )

    def _migrate_generated_table(self, conn: sqlite3.Connection) -> None:
        self._ensure_column(
            conn,
            "generated_combinations",
            "pattern_risk",
            "ALTER TABLE generated_combinations ADD COLUMN pattern_risk INTEGER NOT NULL DEFAULT 0",
        )
        self._ensure_column(
            conn,
            "generated_combinations",
            "pattern_notes",
            "ALTER TABLE generated_combinations ADD COLUMN pattern_notes TEXT NOT NULL DEFAULT ''",
        )

    def load_draws(self) -> pd.DataFrame:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT draw_no, date, n1, n2, n3, n4, n5, n6, bonus
                FROM lotto_draws
                ORDER BY draw_no
                """
            ).fetchall()

        return pd.DataFrame(rows, columns=DRAW_COLUMNS)

    def upsert_draws(self, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0

        self.initialize()
        rows = []
        for _, row in df.iterrows():
            bonus = row.get("bonus", np.nan)
            rows.append(
                (
                    int(row["draw_no"]),
                    str(row.get("date", "")),
                    int(row["n1"]),
                    int(row["n2"]),
                    int(row["n3"]),
                    int(row["n4"]),
                    int(row["n5"]),
                    int(row["n6"]),
                    None if pd.isna(bonus) else int(bonus),
                )
            )

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO lotto_draws (
                    draw_no, date, n1, n2, n3, n4, n5, n6, bonus
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(draw_no) DO UPDATE SET
                    date = excluded.date,
                    n1 = excluded.n1,
                    n2 = excluded.n2,
                    n3 = excluded.n3,
                    n4 = excluded.n4,
                    n5 = excluded.n5,
                    n6 = excluded.n6,
                    bonus = excluded.bonus,
                    updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )

        return len(rows)

    def save_combinations(
        self,
        records: Sequence[CombinationRecord],
        source_draw_no: Optional[int],
    ) -> int:
        if not records:
            return 0

        self.initialize()
        generated_at = datetime.now().isoformat(timespec="microseconds")
        rows = [
            self._combination_row(record, generated_at, source_draw_no)
            for record in records
        ]

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO generated_combinations (
                    generated_at, source_draw_no, numbers_text,
                    n1, n2, n3, n4, n5, n6,
                    total, odd_count, high_count, ac_value, carry_count, score,
                    pattern_risk, pattern_notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        return len(rows)

    @staticmethod
    def _combination_row(
        record: CombinationRecord,
        generated_at: str,
        source_draw_no: Optional[int],
    ) -> Tuple[object, ...]:
        record_source_draw_no = record.source_draw_no or source_draw_no
        return (
            generated_at,
            record_source_draw_no,
            format_numbers(record.numbers),
            record.numbers[0],
            record.numbers[1],
            record.numbers[2],
            record.numbers[3],
            record.numbers[4],
            record.numbers[5],
            record.total,
            record.odd_count,
            record.high_count,
            record.ac_value,
            record.carry_count,
            float(record.score),
            int(record.pattern_risk),
            str(record.pattern_notes),
        )

    def load_latest_combinations(self) -> List[CombinationRecord]:
        self.initialize()
        with self._connect() as conn:
            latest_row = conn.execute(
                """
                SELECT generated_at
                FROM generated_combinations
                ORDER BY generated_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()

            if latest_row is None:
                return []

            rows = conn.execute(
                """
                SELECT n1, n2, n3, n4, n5, n6,
                       total, odd_count, high_count, ac_value, carry_count, score,
                       source_draw_no, pattern_risk, pattern_notes
                FROM generated_combinations
                WHERE generated_at = ?
                ORDER BY id
                """,
                (latest_row[0],),
            ).fetchall()

        return [
            CombinationRecord(
                numbers=(int(row[0]), int(row[1]), int(row[2]), int(row[3]), int(row[4]), int(row[5])),
                total=int(row[6]),
                odd_count=int(row[7]),
                high_count=int(row[8]),
                ac_value=int(row[9]),
                carry_count=int(row[10]),
                score=float(row[11]),
                source_draw_no=None if row[12] is None else int(row[12]),
                pattern_risk=int(row[13] or 0),
                pattern_notes=str(row[14] or ""),
            )
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        alter_sql: str,
    ) -> None:
        columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            conn.execute(alter_sql)


class LottoDataLoader:
    """
    로컬 lotto_history.xlsx를 우선 사용하고, 동행복권 회차 JSON 조회 데이터로
    누락 회차를 증분 업데이트합니다. 정규화된 회차 데이터는 SQLite DB에도
    동기화해 검색/검증용 저장소로 사용합니다.

    - xlsx 존재: xlsx 로드 -> SQLite 동기화 -> JSON 누락 회차 업데이트
    - xlsx 없음 + DB 존재: SQLite 데이터로 분석
    - xlsx/DB/네트워크 모두 불가: 내장 데모 데이터로 UI/알고리즘 검증 가능

    API 이력:
      - 구 API (deprecated): https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo=N
        → 2025년 사이트 개편 이후 HTTP 302 리다이렉트 반환으로 사실상 폐기됨
      - 신규 API (현행):     https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do
        → GET srchDir=center&srchLtEpsd=N → 1회 요청으로 최대 10회차 반환
    """

    # 신규 API (2025 사이트 개편 후 현행)
    NEW_API_URL    = "https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do"
    NEW_API_ORIGIN = "https://www.dhlottery.co.kr"
    # 구 API (deprecated — fallback 전용)
    API_URL = "https://www.dhlottery.co.kr/common.do"
    FIRST_DRAW_DATE = date(2002, 12, 7)

    def __init__(
        self,
        xlsx_path: Optional[Path] = None,
        db_path: Optional[Path] = None,
        timeout: float = 5.0,
    ) -> None:
        self.xlsx_path = xlsx_path or EXCEL_HISTORY_FILE
        self.database = LottoDatabase(db_path or SQLITE_DB_FILE)
        self.timeout = timeout

    def load_history(
        self,
        config: AnalysisConfig,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Tuple[pd.DataFrame, str, List[str]]:
        """전체 분석용 당첨 번호 히스토리를 로드합니다."""
        warnings: List[str] = []
        base_df, source_base = self._load_local_history(warnings, progress)
        latest_no, network_ok = self._resolve_latest_no(config, base_df, warnings, progress)
        if latest_no <= 0:
            return self._demo_result("네트워크, xlsx, SQLite DB를 모두 사용할 수 없어 내장 데모 데이터를 사용했습니다.", warnings)

        start_draw = max(NUMBER_MIN, int(config.start_draw))
        base_df = self._sanitize_df(base_df)
        data_slice = self._draw_range(base_df, start_draw, latest_no)
        missing_draws = self._missing_draw_numbers(data_slice, start_draw, latest_no)
        json_updated = False

        if network_ok and missing_draws:
            fetched_rows = self._fetch_missing_rows(missing_draws, warnings, progress)
            if fetched_rows:
                source_base = "동행복권 JSON + SQLite DB" if base_df.empty else source_base
                base_df = self._merge_and_persist(base_df, fetched_rows, warnings, progress)
                data_slice = self._draw_range(base_df, start_draw, latest_no)
                json_updated = True

        if data_slice.empty:
            return self._demo_result("분석 가능한 실제 회차 데이터가 없어 내장 데모 데이터를 사용했습니다.", warnings)

        data_slice = self._sanitize_df(data_slice)
        if len(data_slice) < 10:
            warnings.append("분석 데이터가 10회차 미만입니다. 통계 점수의 안정성이 낮을 수 있습니다.")

        source_name = self._source_name(source_base, json_updated, network_ok, config)
        return data_slice, source_name, warnings

    def _load_local_history(
        self,
        warnings: List[str],
        progress: Optional[Callable[[str], None]],
    ) -> Tuple[pd.DataFrame, str]:
        self._emit(progress, "Layer 1: lotto_history.xlsx 확인 중...")
        excel_df = self._load_excel()
        if self.xlsx_path.exists() and excel_df.empty:
            warnings.append("lotto_history.xlsx를 읽지 못했거나 유효한 회차 데이터가 없습니다.")

        try:
            db_df = self.database.load_draws()
        except Exception as exc:
            db_df = pd.DataFrame(columns=DRAW_COLUMNS)
            warnings.append(f"SQLite 초기화/로드 실패: {exc}")

        if not excel_df.empty:
            self._emit(progress, f"xlsx 로드: {len(excel_df):,}개 회차")
            self._sync_database(excel_df, "SQLite 동기화", warnings, progress)
            return excel_df, "로컬 xlsx + SQLite DB"

        if not db_df.empty:
            self._emit(progress, f"SQLite 로드: {len(db_df):,}개 회차")
            warnings.append("lotto_history.xlsx를 읽지 못해 SQLite DB 데이터를 사용했습니다.")
            return db_df, "SQLite DB"

        return pd.DataFrame(columns=DRAW_COLUMNS), "내장 데모 데이터"

    def _resolve_latest_no(
        self,
        config: AnalysisConfig,
        base_df: pd.DataFrame,
        warnings: List[str],
        progress: Optional[Callable[[str], None]],
    ) -> Tuple[int, bool]:
        latest_no = config.max_draw if config.max_draw > 0 else 0
        network_ok = requests is not None

        if not network_ok:
            warnings.append("requests 패키지가 없어 네트워크 조회를 건너뛰고 로컬 데이터로 진행했습니다.")
            return latest_no or self._latest_local_no(base_df, warnings), False

        if latest_no <= 0:
            try:
                self._emit(progress, "동행복권 최신 회차 탐색 중...")
                latest_no = self.find_latest_draw_no()
                self._emit(progress, f"최신 회차 감지: {latest_no}")
            except Exception as exc:
                warnings.append(f"온라인 최신 회차 확인 불가: {exc}")
                latest_no = self._latest_local_no(base_df, warnings)
                if latest_no > 0:
                    self._emit(progress, f"로컬 최신 회차 사용: {latest_no}")
                return latest_no, False

        return latest_no, network_ok

    def _latest_local_no(self, base_df: pd.DataFrame, warnings: List[str]) -> int:
        if base_df.empty:
            return 0
        warnings.append("최신 회차를 네트워크로 확인하지 못해 로컬 데이터의 마지막 회차를 사용했습니다.")
        return int(base_df["draw_no"].max())

    def _fetch_missing_rows(
        self,
        missing_draws: Sequence[int],
        warnings: List[str],
        progress: Optional[Callable[[str], None]],
    ) -> List[Dict[str, object]]:
        """누락 회차를 조회합니다.

        신규 API는 1회 요청으로 최대 10회차를 반환하므로, step=9 간격의 center를 사용해
        모든 누락 회차를 효율적으로 배치 조회합니다. 기존 대비 최대 10배 빠릅니다.
        배치에서 빠진 회차는 구 API로 개별 재시도합니다.
        """
        self._emit(progress, f"동행복권 데이터 조회: 누락 {len(missing_draws):,}개 회차")
        fetched_map: Dict[int, Dict[str, object]] = {}
        missing_set = set(int(n) for n in missing_draws)
        sorted_missing = sorted(missing_set)
        fail_count = 0

        # ── 신규 API: 배치 조회 (center 기준 ±5회차 → step=9로 전체 커버) ──────
        if requests is not None:
            try:
                session = self._make_session()
                centers = list(range(sorted_missing[0], sorted_missing[-1] + 1, 9))
                # 마지막 회차가 window 밖에 있을 수 있으므로 항상 마지막 회차를 center로 추가
                if not centers or centers[-1] < sorted_missing[-1]:
                    centers.append(sorted_missing[-1])
                total_batches = len(centers)

                for batch_idx, center in enumerate(centers):
                    if len(fetched_map) >= len(missing_set):
                        break  # 모두 수집 완료

                    try:
                        draws = self._fetch_batch_new(session, center)
                        for d in draws:
                            if (d.draw_no in missing_set
                                    and d.draw_no not in fetched_map
                                    and self._is_valid_numbers(d.numbers)):
                                fetched_map[d.draw_no] = self._draw_to_row(d)
                    except Exception:
                        fail_count += 1

                    if batch_idx % 25 == 0 or batch_idx == total_batches - 1:
                        self._emit(
                            progress,
                            f"배치 조회 진행: {len(fetched_map):,}/{len(missing_set):,} "
                            f"(배치 {batch_idx + 1}/{total_batches})",
                        )
                        time.sleep(0.02)
            except Exception as exc:
                warnings.append(f"신규 API 배치 조회 중 오류: {exc}")

        # ── 배치에서 빠진 회차 → 구 API 개별 재시도 ──────────────────────────
        remaining = [n for n in sorted_missing if n not in fetched_map]
        if remaining:
            self._emit(progress, f"개별 재조회: {len(remaining):,}개 회차 (구 API)")
            for idx, draw_no in enumerate(remaining, 1):
                try:
                    draw = self._fetch_draw_legacy(draw_no)
                    if draw is None:
                        fail_count += 1
                        continue
                    fetched_map[draw.draw_no] = self._draw_to_row(draw)
                except Exception:
                    fail_count += 1

                if idx % 25 == 0 or idx == len(remaining):
                    self._emit(progress, f"개별 조회 진행: {idx:,}/{len(remaining):,}")
                    time.sleep(0.02)

        if fail_count:
            warnings.append(
                f"{fail_count:,}개 회차는 조회 실패 또는 미공개 상태라 건너뛰었습니다."
            )

        return list(fetched_map.values())

    def _merge_and_persist(
        self,
        base_df: pd.DataFrame,
        fetched_rows: Sequence[Dict[str, object]],
        warnings: List[str],
        progress: Optional[Callable[[str], None]],
    ) -> pd.DataFrame:
        fetched_df = pd.DataFrame(fetched_rows, columns=DRAW_COLUMNS)
        merged = self._sanitize_df(pd.concat([base_df, fetched_df], ignore_index=True))

        save_warning = self._save_excel(merged)
        if save_warning:
            warnings.append(save_warning)

        self._sync_database(merged, "SQLite 업데이트", warnings, progress)
        self._emit(progress, "xlsx/SQLite 업데이트 완료")
        return merged

    def _sync_database(
        self,
        df: pd.DataFrame,
        label: str,
        warnings: List[str],
        progress: Optional[Callable[[str], None]],
    ) -> None:
        try:
            synced = self.database.upsert_draws(df)
            self._emit(progress, f"{label}: {synced:,}개 회차")
        except Exception as exc:
            warnings.append(f"{label} 실패: {exc}")

    @staticmethod
    def _draw_range(df: pd.DataFrame, start_draw: int, latest_no: int) -> pd.DataFrame:
        return df[
            (df["draw_no"] >= start_draw) & (df["draw_no"] <= latest_no)
        ].copy()

    def _demo_result(self, warning: str, warnings: List[str]) -> Tuple[pd.DataFrame, str, List[str]]:
        warnings.append(warning)
        return self._make_demo_history(), "내장 데모 데이터", warnings

    @staticmethod
    def _source_name(
        source_base: str,
        json_updated: bool,
        network_ok: bool,
        config: AnalysisConfig,
    ) -> str:
        if source_base.startswith("동행복권 JSON"):
            return source_base
        if json_updated:
            return f"{source_base} + 동행복권 JSON 증분 업데이트"
        if network_ok and config.max_draw <= 0:
            return f"{source_base} + 동행복권 JSON 최신 회차 확인"
        return source_base

    def find_latest_draw_no(self) -> int:
        """
        최초 추첨일 기준 주차로 최신 회차 후보를 추정하고, 신규 API로 실제 최신 회차를 확인합니다.
        신규 API는 한 번 요청으로 최대 10개 회차를 반환하므로 구 API보다 빠릅니다.
        동행복권 측의 회차 공개 지연이나 점검을 고려해 여유분을 둡니다.
        """
        estimated = ((date.today() - self.FIRST_DRAW_DATE).days // 7) + 1
        hint = estimated + 4
        lower_bound = max(1, hint - 40)

        # ── 신규 API 우선 시도 ─────────────────────────────────────────────────
        # hint(=estimated+4) 부터 1씩 내려가며 첫 응답을 찾음.
        # 보통 hint와 실제 최신 회차의 차이는 4~6 이내이므로 API 호출 낭비가 없음.
        if requests is not None:
            try:
                session = self._make_session()
                for offset in range(50):          # 최대 50회 (약 1년치 여유)
                    candidate = hint - offset
                    if candidate < 1:
                        break
                    draws = self._fetch_batch_new(session, candidate)
                    if draws:
                        return max(d.draw_no for d in draws)
            except Exception:
                pass  # 신규 API 실패 → 구 API fallback

        # ── 구 API fallback (역방향 스캔) ─────────────────────────────────────
        for draw_no in range(hint, lower_bound - 1, -1):
            draw = self._fetch_draw_legacy(draw_no)
            if draw is not None:
                return draw.draw_no

        raise LottoAnalysisError("최근 40개 후보 회차에서 성공 응답을 찾지 못했습니다.")

    def fetch_draw(self, draw_no: int) -> Optional[LottoDraw]:
        """동행복권 회차를 단건 조회합니다. 신규 API → 구 API 순으로 시도합니다."""
        if requests is None:
            return None

        # 신규 API: center 요청으로 최대 10개 회차에서 해당 회차를 찾음
        try:
            session = self._make_session()
            draws = self._fetch_batch_new(session, draw_no)
            for d in draws:
                if d.draw_no == int(draw_no):
                    return d
            # 응답은 왔지만 해당 회차가 없는 경우 → 미공개 회차
            if draws:
                return None
        except Exception:
            pass  # 신규 API 실패 → 구 API fallback

        return self._fetch_draw_legacy(draw_no)

    # ── 신규 API 헬퍼 ──────────────────────────────────────────────────────────

    def _make_session(self) -> "requests.Session":
        """동행복권 세션 (홈페이지 방문으로 초기 쿠키 획득)."""
        session = requests.Session()
        session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        try:
            session.get(self.NEW_API_ORIGIN + "/", timeout=self.timeout, allow_redirects=True)
        except Exception:
            pass
        return session

    @staticmethod
    def _new_api_headers() -> Dict[str, str]:
        return {
            "Accept":           "application/json, text/javascript, */*; q=0.01",
            "Accept-Language":  "ko-KR,ko;q=0.9",
            "Referer":          "https://www.dhlottery.co.kr/lt645/result",
            "X-Requested-With": "XMLHttpRequest",
        }

    def _fetch_batch_new(
        self,
        session: "requests.Session",
        center_draw_no: int,
    ) -> List[LottoDraw]:
        """신규 API(selectPstLt645InfoNew.do)로 center_draw_no 기준 최대 10개 회차를 조회합니다.

        반환 데이터 필드 매핑 (동행복권 신규 → 내부 표준):
          ltEpsd         → draw_no
          tm1WnNo~tm6WnNo → numbers (n1~n6)
          bnsWnNo        → bonus
          ltRflYmd       → draw_date  (YYYYMMDD → YYYY-MM-DD)
        """
        resp = session.get(
            self.NEW_API_URL,
            params={"srchDir": "center", "srchLtEpsd": str(int(center_draw_no))},
            headers=self._new_api_headers(),
            timeout=self.timeout,
            allow_redirects=False,
        )
        if resp.is_redirect or resp.is_permanent_redirect:
            raise LottoAnalysisError(
                f"신규 API 리다이렉트 (HTTP {resp.status_code}, "
                f"Location: {resp.headers.get('location', '')})"
            )
        resp.raise_for_status()

        payload = resp.json()
        rc = payload.get("resultCode", "")
        if rc and rc != "success":
            raise LottoAnalysisError(
                f"신규 API 오류 코드: {rc} — {payload.get('resultMessage', '')}"
            )

        data  = payload.get("data") or {}
        items = data.get("list") or []
        return [d for d in (self._parse_new_api_item(item) for item in items) if d is not None]

    @staticmethod
    def _parse_new_api_item(item: Dict) -> Optional[LottoDraw]:
        """신규 API 응답 단일 항목을 LottoDraw로 변환합니다."""
        try:
            draw_no  = int(item["ltEpsd"])
            numbers  = tuple(int(item[f"tm{i}WnNo"]) for i in range(1, 7))
            bns_raw  = item.get("bnsWnNo")
            bonus    = int(bns_raw) if bns_raw else None
            raw_date = str(item.get("ltRflYmd", ""))
            draw_date = (
                f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                if len(raw_date) == 8 else raw_date
            )
            return LottoDraw(
                draw_no=draw_no,
                draw_date=draw_date,
                numbers=numbers,   # type: ignore[arg-type]
                bonus=bonus,
            )
        except (KeyError, ValueError, TypeError):
            return None

    # ── 구 API (fallback) ──────────────────────────────────────────────────────

    def _fetch_draw_legacy(self, draw_no: int) -> Optional[LottoDraw]:
        """구 API(common.do?method=getLottoNumber)로 단건 조회합니다 (fallback 전용).

        주의: 동행복권 사이트 개편(2025년) 이후 이 엔드포인트는 HTTP 302를 반환하므로
        일반적인 환경에서는 사용 불가합니다. 예외적으로 접근 가능한 환경을 위해 남겨둡니다.
        """
        if requests is None:
            return None

        params  = {"method": "getLottoNumber", "drwNo": int(draw_no)}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 LottoGridAI/1.0 "
                "(educational analysis tool; contact: local-user)"
            )
        }

        response = requests.get(
            self.API_URL,
            params=params,
            headers=headers,
            timeout=self.timeout,
            allow_redirects=False,
        )
        if response.is_redirect or response.is_permanent_redirect:
            raise LottoAnalysisError(self._api_response_error(response, "리다이렉트를"))
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as exc:
            raise LottoAnalysisError(self._api_response_error(response, "JSON이 아닌 응답을")) from exc

        if not isinstance(payload, dict):
            raise LottoAnalysisError("동행복권 구 API 응답 형식이 예상과 다릅니다.")

        if payload.get("returnValue") != "success":
            return None

        numbers   = tuple(int(payload[f"drwtNo{i}"]) for i in range(1, 7))
        bonus     = int(payload["bnusNo"]) if payload.get("bnusNo") else None
        draw_date = str(payload.get("drwNoDate", ""))

        if not self._is_valid_numbers(numbers):
            raise LottoAnalysisError(f"{draw_no}회차 번호 형식이 올바르지 않습니다: {numbers}")

        return LottoDraw(
            draw_no=int(payload.get("drwNo", draw_no)),
            draw_date=draw_date,
            numbers=numbers,  # type: ignore[arg-type]
            bonus=bonus,
        )

    @staticmethod
    def _api_response_error(response, reason: str) -> str:
        content_type = response.headers.get("content-type", "unknown")
        location = response.headers.get("location")
        location_text = f", 이동 위치: {location}" if location else ""
        return (
            f"동행복권 구 API가 예상한 JSON 대신 {reason} 반환했습니다 "
            f"(HTTP {response.status_code}, Content-Type: {content_type}{location_text})."
        )

    def _load_excel(self) -> pd.DataFrame:
        if not self.xlsx_path.exists():
            return pd.DataFrame(columns=DRAW_COLUMNS)

        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Workbook contains no default style.*",
                    category=UserWarning,
                    module="openpyxl.styles.stylesheet",
                )
                df = pd.read_excel(self.xlsx_path)
            return self._normalize_excel_df(df)
        except Exception:
            return pd.DataFrame(columns=DRAW_COLUMNS)

    def _save_excel(self, df: pd.DataFrame) -> Optional[str]:
        try:
            self.xlsx_path.parent.mkdir(parents=True, exist_ok=True)
            clean = self._sanitize_df(df)
            clean.to_excel(self.xlsx_path, index=False, engine="openpyxl")
            return None
        except Exception as exc:
            return f"lotto_history.xlsx 저장 실패: {exc}"

    def _normalize_excel_df(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=DRAW_COLUMNS)

        if all(col in df.columns for col in DRAW_COLUMNS):
            return self._sanitize_df(df)

        alias_df = self._normalize_by_alias(df)
        if not alias_df.empty:
            return alias_df
        return self._normalize_by_position(df)

    def _normalize_by_alias(self, df: pd.DataFrame) -> pd.DataFrame:
        normalized_columns = {self._normalize_column_name(col): col for col in df.columns}
        mapped: Dict[str, object] = {}
        for target, names in self._column_aliases().items():
            for name in names:
                source = normalized_columns.get(self._normalize_column_name(name))
                if source is not None:
                    mapped[target] = df[source]
                    break

        if all(col in mapped for col in ["draw_no", "n1", "n2", "n3", "n4", "n5", "n6"]):
            normalized = pd.DataFrame({col: mapped.get(col, "") for col in DRAW_COLUMNS})
            return self._sanitize_df(normalized)

        return pd.DataFrame(columns=DRAW_COLUMNS)

    @staticmethod
    def _normalize_column_name(value: object) -> str:
        return str(value).strip().lower().replace(" ", "").replace("_", "")

    @staticmethod
    def _column_aliases() -> Dict[str, List[str]]:
        return {
            "draw_no": ["drawno", "drwno", "회차", "추첨회차"],
            "date": ["date", "drawdate", "drwnodate", "추첨일", "추첨일자"],
            "n1": ["n1", "num1", "number1", "drwtno1", "번호1"],
            "n2": ["n2", "num2", "number2", "drwtno2", "번호2"],
            "n3": ["n3", "num3", "number3", "drwtno3", "번호3"],
            "n4": ["n4", "num4", "number4", "drwtno4", "번호4"],
            "n5": ["n5", "num5", "number5", "drwtno5", "번호5"],
            "n6": ["n6", "num6", "number6", "drwtno6", "번호6"],
            "bonus": ["bonus", "bnusno", "보너스", "보너스번호"],
        }

    def _normalize_by_position(self, df: pd.DataFrame) -> pd.DataFrame:
        # 기존 lotto_history.xlsx는 헤더가 깨져 있어 위치 기반으로 읽습니다.
        # B열=회차, C~H열=당첨번호 6개, I열=보너스 번호 형태를 우선 시도합니다.
        candidates: List[pd.DataFrame] = []
        positional_specs = [(1, 2), (0, 1)]
        for draw_col, first_number_col in positional_specs:
            bonus_col = first_number_col + 6
            if df.shape[1] <= bonus_col:
                continue
            candidate = pd.DataFrame(
                {
                    "draw_no": df.iloc[:, draw_col],
                    "date": "",
                    "n1": df.iloc[:, first_number_col],
                    "n2": df.iloc[:, first_number_col + 1],
                    "n3": df.iloc[:, first_number_col + 2],
                    "n4": df.iloc[:, first_number_col + 3],
                    "n5": df.iloc[:, first_number_col + 4],
                    "n6": df.iloc[:, first_number_col + 5],
                    "bonus": df.iloc[:, bonus_col],
                }
            )
            candidates.append(self._sanitize_df(candidate))

        if candidates:
            return max(candidates, key=len)

        return pd.DataFrame(columns=DRAW_COLUMNS)

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


