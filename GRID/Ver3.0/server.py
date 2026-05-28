"""Lotto Grid AI Analyzer - Web App Ver3.0 (FastAPI Backend)"""
from __future__ import annotations

import os
import sys
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests as _req

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent
VER2_DIR   = BASE_DIR.parent / "Ver 2.0"
ROOT_DIR   = BASE_DIR.parent.parent
_xlsx_env  = os.environ.get("LOTTO_XLSX")
XLSX_PATH  = Path(_xlsx_env) if _xlsx_env else ROOT_DIR / "lotto_history.xlsx"
DB_PATH    = BASE_DIR / "lotto_history.db"
STATIC_DIR = BASE_DIR / "static"

sys.path.insert(0, str(VER2_DIR))

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from lotto_grid_ai.models     import AnalysisConfig
from lotto_grid_ai.storage    import LottoDataLoader
from lotto_grid_ai.analysis   import LottoAnalyzer
from lotto_grid_ai.generation import CombinationGenerator
from lotto_grid_ai.grid       import GridMapper

# ── 동행복권 API 자동 연동 ──────────────────────────────────────────────────────
DH_API_URL      = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={}"
FIRST_DRAW_DATE = date(2002, 12, 7)   # 1회 추첨일 (토요일)

_sync_lock   = threading.Lock()
_sync_status: Dict[str, Any] = {
    "state":         "idle",   # idle | syncing | done | error
    "last_sync":     None,     # ISO UTC 문자열
    "fetched":       0,        # 이번 동기화에서 추가된 회차 수
    "max_draw_in_db": 0,       # DB 최신 회차번호
    "message":       "동기화 대기 중",
}


def _db_max_draw_no() -> int:
    """DB에서 현재 최고 회차번호 반환. 없으면 0 반환."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur  = conn.execute("SELECT MAX(draw_no) FROM lotto_draws")
        row  = cur.fetchone()
        conn.close()
        return int(row[0]) if row and row[0] else 0
    except Exception:
        return 0


def _init_db():
    """lotto_draws / generated_predictions 테이블이 없으면 생성."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lotto_draws (
            draw_no    INTEGER PRIMARY KEY,
            date       TEXT,
            n1         INTEGER, n2 INTEGER, n3 INTEGER,
            n4         INTEGER, n5 INTEGER, n6 INTEGER,
            bonus      INTEGER,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS generated_predictions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            saved_at   TEXT NOT NULL,
            target_no  INTEGER NOT NULL,
            rank       INTEGER NOT NULL,
            n1 INTEGER, n2 INTEGER, n3 INTEGER,
            n4 INTEGER, n5 INTEGER, n6 INTEGER,
            score      REAL,
            start_draw INTEGER,
            end_draw   INTEGER
        )
    """)
    conn.commit()
    conn.close()


def _estimate_latest_draw_no() -> int:
    """오늘 날짜 기준으로 최신 회차번호 추정 (여유분 +2 포함)."""
    try:
        import pytz
        kst   = pytz.timezone("Asia/Seoul")
        today = datetime.now(kst).date()
    except ImportError:
        today = (datetime.utcnow() + timedelta(hours=9)).date()
    days      = (today - FIRST_DRAW_DATE).days
    estimated = days // 7 + 1
    return estimated + 2   # API가 없으면 멈추므로 여유분 포함


def _fetch_draw(draw_no: int) -> Optional[Dict]:
    """동행복권 API에서 특정 회차 데이터 조회."""
    try:
        resp = _req.get(DH_API_URL.format(draw_no), timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("returnValue") != "success":
            return None
        return data
    except Exception:
        return None


def _upsert_draw_record(data: Dict):
    """API 응답 데이터를 DB에 저장 (UPSERT)."""
    now_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    conn    = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        INSERT INTO lotto_draws
            (draw_no, date, n1, n2, n3, n4, n5, n6, bonus, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(draw_no) DO UPDATE SET
            date=excluded.date,
            n1=excluded.n1, n2=excluded.n2, n3=excluded.n3,
            n4=excluded.n4, n5=excluded.n5, n6=excluded.n6,
            bonus=excluded.bonus, updated_at=excluded.updated_at
    """, (
        data["drwNo"],    data["drwNoDate"],
        data["drwtNo1"],  data["drwtNo2"],  data["drwtNo3"],
        data["drwtNo4"],  data["drwtNo5"],  data["drwtNo6"],
        data["bnusNo"],   now_str,
    ))
    conn.commit()
    conn.close()


def sync_draws(force_full: bool = False):
    """동행복권 API에서 누락된 회차를 순차 동기화."""
    global _sync_status

    # 이미 동기화 중이면 무시
    with _sync_lock:
        if _sync_status["state"] == "syncing":
            return
        _sync_status.update({"state": "syncing", "fetched": 0, "message": "동기화 시작…"})

    try:
        _init_db()
        start_from       = 1 if force_full else (_db_max_draw_no() + 1)
        estimated_latest = _estimate_latest_draw_no()
        fetched_count    = 0

        for draw_no in range(start_from, estimated_latest + 1):
            data = _fetch_draw(draw_no)
            if data is None:
                break   # 해당 회차 없음 → 종료
            _upsert_draw_record(data)
            fetched_count += 1
            with _sync_lock:
                _sync_status["fetched"]       = fetched_count
                _sync_status["max_draw_in_db"] = draw_no
                _sync_status["message"]        = f"{draw_no}회 동기화 중…"

        max_in_db = _db_max_draw_no()
        now_str   = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        with _sync_lock:
            _sync_status.update({
                "state":          "done",
                "last_sync":      now_str,
                "max_draw_in_db": max_in_db,
                "message":        f"완료: {fetched_count}회차 추가, 최신 {max_in_db}회",
            })
    except Exception as exc:
        with _sync_lock:
            _sync_status.update({"state": "error", "message": str(exc)})


def _background_sync_loop():
    """시작 즉시 동기화 → 이후 1시간마다 반복."""
    import time
    sync_draws()
    while True:
        time.sleep(3600)
        sync_draws()


# ── FastAPI 라이프사이클 ──────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI):
    t = threading.Thread(target=_background_sync_loop, daemon=True)
    t.start()
    yield


# ── 앱 생성 ───────────────────────────────────────────────────────────────────
app = FastAPI(title="로또번호 랜덤 생성", lifespan=lifespan)

# ── Static 파일 서빙 ──────────────────────────────────────────────────────────
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── 인메모리 분석 결과 캐시 ──────────────────────────────────────────────────
_cached_result     = None
_cached_config_key: Optional[str] = None


# ── Pydantic 요청 스키마 ──────────────────────────────────────────────────────
class ConfigRequest(BaseModel):
    start_draw: int = 1
    max_draw: int = 0
    deadzone_window: int = 25
    top_candidate_count: int = 20
    output_limit: int = 5
    recent_weight: int = 40
    missing_weight: int = 20
    square_weight: int = 0
    deadzone_weight: int = 15
    zone_weight: int = 15
    mix_previous_ratio: int = 5
    max_overlap: int = 3
    max_popularity_risk: int = 3
    backtest_rounds: int = 100
    backtest_train_window: int = 150
    sum_min: int = 100
    sum_max: int = 170
    min_ac: int = 7
    odd_min: int = 2
    odd_max: int = 4
    high_min: int = 2
    high_max: int = 4


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────
def _to_config(req: ConfigRequest) -> AnalysisConfig:
    return AnalysisConfig(**req.model_dump())


def _config_key(req: ConfigRequest) -> str:
    d = req.model_dump()
    return str(sorted(d.items()))


def _next_saturday(from_dt: datetime) -> datetime:
    """주어진 날짜/시간으로부터 다음 토요일 20:45:00(KST) 반환."""
    days_ahead = (5 - from_dt.weekday()) % 7
    if days_ahead == 0:
        draw_time = from_dt.replace(hour=20, minute=45, second=0, microsecond=0)
        if from_dt >= draw_time:
            days_ahead = 7
    sat = from_dt + timedelta(days=days_ahead)
    return sat.replace(hour=20, minute=45, second=0, microsecond=0)


def _serialize_result(result) -> Dict[str, Any]:
    cells: List[Dict] = []
    score_lookup: Dict[int, float] = {}

    for _, row in result.score_table.iterrows():
        n = int(row["number"])
        s = round(float(row["score"]), 1)
        score_lookup[n] = s

    for n in range(1, 46):
        r, c = GridMapper.number_to_pos(n)
        cells.append({"number": n, "row": r, "col": c, "score": score_lookup.get(n, 0.0)})

    table_rows = []
    for _, row in result.score_table.iterrows():
        table_rows.append({
            "number":            int(row["number"]),
            "score":             round(float(row["score"]), 1),
            "freq_recent_count": int(row["freq_recent_count"]),
            "missing_gap":       int(row["missing_gap"]),
            "square_hit_count":  int(row["square_hit_count"]),
            "is_deadzone":       bool(row["is_deadzone"]),
            "is_latest":         bool(row["is_latest"]),
            "is_prev_square":    bool(row["is_prev_square"]),
        })

    bt = result.backtest_summary
    return {
        "source_name":            result.source_name,
        "total_draws":            len(result.df),
        "warnings":               result.warnings,
        "latest_draw_no":         result.latest_draw.draw_no,
        "latest_draw_date":       result.latest_draw.draw_date,
        "latest_numbers":         list(result.latest_draw.numbers),
        "latest_bonus":           result.latest_draw.bonus,
        "prev_square_numbers":    sorted(result.prev_square_numbers),
        "deadzone_numbers":       sorted(result.deadzone_numbers),
        "final_expected_numbers": list(result.final_expected_numbers),
        "candidate_pool":         list(result.candidate_pool),
        "heatmap_cells":          cells,
        "score_table":            table_rows,
        "backtest": {
            "rounds":           bt.rounds,
            "avg_hits":         round(bt.avg_hits, 2),
            "random_avg_hits":  round(bt.random_avg_hits, 2),
            "hit3_rate":        round(bt.hit3_rate * 100, 1),
            "random_hit3_rate": round(bt.random_hit3_rate * 100, 1),
            "hit4_rate":        round(bt.hit4_rate * 100, 1),
            "random_hit4_rate": round(bt.random_hit4_rate * 100, 1),
            "best_hit_count":   bt.best_hit_count,
            "last_hit_count":   bt.last_hit_count,
        },
    }


def _run_analysis(req: ConfigRequest):
    global _cached_result, _cached_config_key
    load_key = str((req.start_draw, req.max_draw))
    config   = _to_config(req)
    loader   = LottoDataLoader(xlsx_path=XLSX_PATH, db_path=DB_PATH)

    if _cached_result is not None and _cached_config_key == load_key:
        result = LottoAnalyzer().analyze(
            _cached_result.df, config,
            _cached_result.source_name, []
        )
    else:
        df, source_name, warnings = loader.load_history(config)
        result = LottoAnalyzer().analyze(df, config, source_name, warnings)

    _cached_result     = result
    _cached_config_key = load_key
    return result


# ── 라우트 ────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/favicon.png")
def favicon():
    fp = STATIC_DIR / "favicon.png"
    if fp.exists():
        return FileResponse(str(fp), media_type="image/png")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/api/sync_status")
def get_sync_status():
    """동기화 상태 조회."""
    with _sync_lock:
        return dict(_sync_status)


@app.post("/api/sync")
def manual_sync():
    """수동 동기화 트리거."""
    with _sync_lock:
        state = _sync_status["state"]
    if state == "syncing":
        return {"status": "already_syncing", "message": "동기화가 이미 진행 중입니다"}
    t = threading.Thread(target=sync_draws, daemon=True)
    t.start()
    return {"status": "started", "message": "동기화를 시작했습니다"}


@app.get("/api/info")
def get_info():
    """최신 회차 정보 + 다음 추첨 일정 반환 (분석 없이 빠른 응답)."""
    try:
        loader = LottoDataLoader(xlsx_path=XLSX_PATH, db_path=DB_PATH)
        config = AnalysisConfig(start_draw=1, max_draw=0)
        df, source_name, _ = loader.load_history(config)
        if df is None or df.empty:
            # 동기화 중이면 안내 메시지
            with _sync_lock:
                sync_msg = _sync_status["message"]
                sync_state = _sync_status["state"]
            if sync_state == "syncing":
                return JSONResponse(
                    {"status": "syncing", "message": f"데이터 로딩 중… ({sync_msg})"},
                    status_code=202,
                )
            return JSONResponse({"status": "error", "message": "데이터 없음"}, 500)

        latest      = df.iloc[-1]
        latest_no   = int(latest["draw_no"])
        latest_date = str(latest.get("date", ""))
        numbers     = [int(latest[f"n{i}"]) for i in range(1, 7)]
        bonus_raw   = latest.get("bonus", None)
        bonus       = int(bonus_raw) if bonus_raw is not None and pd.notna(bonus_raw) else None

        try:
            import pytz
            kst  = pytz.timezone("Asia/Seoul")
            now  = datetime.now(kst)
        except ImportError:
            now  = datetime.utcnow() + timedelta(hours=9)

        next_sat = _next_saturday(now)
        next_no  = latest_no + 1

        with _sync_lock:
            sync_info = dict(_sync_status)

        return {
            "status":          "ok",
            "latest_draw_no":  latest_no,
            "latest_date":     latest_date,
            "latest_numbers":  numbers,
            "latest_bonus":    bonus,
            "next_draw_no":    next_no,
            "next_draw_date":  next_sat.strftime("%Y-%m-%d"),
            "next_draw_ts":    int(next_sat.timestamp()),
            "source_name":     source_name,
            "sync":            sync_info,
        }
    except Exception as exc:
        import traceback
        return JSONResponse(
            {"status": "error", "message": str(exc), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.post("/api/analyze")
def analyze(req: ConfigRequest):
    try:
        result = _run_analysis(req)
        return {"status": "ok", "data": _serialize_result(result)}
    except Exception as exc:
        import traceback
        return JSONResponse(
            {"status": "error", "message": str(exc), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.post("/api/generate")
def generate(req: ConfigRequest):
    try:
        result  = _run_analysis(req)
        records, gen_warns = CombinationGenerator().generate(result, _to_config(req))
        combos  = [
            {
                "rank":          i + 1,
                "numbers":       list(r.numbers),
                "total":         r.total,
                "odd_count":     r.odd_count,
                "high_count":    r.high_count,
                "ac_value":      r.ac_value,
                "carry_count":   r.carry_count,
                "pattern_risk":  r.pattern_risk,
                "pattern_notes": r.pattern_notes,
                "score":         round(float(r.score), 2),
            }
            for i, r in enumerate(records)
        ]

        # ── 예상 번호 자동 저장 ──────────────────────────────────────────────────
        try:
            _init_db()
            now_str   = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            target_no = result.latest_draw.draw_no + 1
            conn = sqlite3.connect(str(DB_PATH))
            for combo in combos:
                nums = combo["numbers"]
                conn.execute("""
                    INSERT INTO generated_predictions
                        (session_id, saved_at, target_no, rank,
                         n1, n2, n3, n4, n5, n6, score, start_draw, end_draw)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    now_str, now_str, target_no, combo["rank"],
                    nums[0], nums[1], nums[2], nums[3], nums[4], nums[5],
                    combo["score"], req.start_draw, req.max_draw,
                ))
            conn.commit()
            conn.close()
        except Exception:
            pass  # 저장 실패해도 생성 결과는 정상 반환

        return {
            "status":       "ok",
            "combinations": combos,
            "warnings":     gen_warns,
            "data":         _serialize_result(result),
        }
    except Exception as exc:
        import traceback
        return JSONResponse(
            {"status": "error", "message": str(exc), "trace": traceback.format_exc()},
            status_code=500,
        )


# ── 내 번호 이력 ──────────────────────────────────────────────────────────────
@app.get("/api/my_history")
def my_history():
    """저장된 예상 번호 이력 + 실제 추첨 결과 비교."""
    try:
        _init_db()
        conn  = sqlite3.connect(str(DB_PATH))
        preds = conn.execute("""
            SELECT id, session_id, saved_at, target_no, rank,
                   n1, n2, n3, n4, n5, n6, score, start_draw, end_draw
            FROM generated_predictions
            ORDER BY saved_at DESC
        """).fetchall()

        history = []
        for row in preds:
            (rid, session_id, saved_at, target_no, rank,
             n1, n2, n3, n4, n5, n6, score, start_draw, end_draw) = row
            numbers = [n1, n2, n3, n4, n5, n6]

            # 실제 추첨 결과 비교
            actual = conn.execute(
                "SELECT n1,n2,n3,n4,n5,n6,bonus FROM lotto_draws WHERE draw_no=?",
                (target_no,)
            ).fetchone()

            match_count   = None
            bonus_match   = False
            actual_numbers = None
            actual_bonus  = None
            if actual:
                actual_numbers = list(actual[:6])
                actual_bonus   = actual[6]
                match_count    = len(set(numbers) & set(actual_numbers))
                bonus_match    = bool(actual_bonus and actual_bonus in numbers)

            history.append({
                "id":             rid,
                "session_id":     session_id,
                "saved_at":       saved_at,
                "target_no":      target_no,
                "rank":           rank,
                "numbers":        numbers,
                "score":          score,
                "start_draw":     start_draw,
                "end_draw":       end_draw,
                "match_count":    match_count,
                "bonus_match":    bonus_match,
                "actual_numbers": actual_numbers,
                "actual_bonus":   actual_bonus,
            })
        conn.close()
        return {"status": "ok", "history": history}
    except Exception as exc:
        import traceback
        return JSONResponse(
            {"status": "error", "message": str(exc), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.delete("/api/my_history/session/{session_id:path}")
def delete_session(session_id: str):
    """특정 세션(한 번의 생성 묶음) 전체 삭제."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("DELETE FROM generated_predictions WHERE session_id=?", (session_id,))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.delete("/api/my_history")
def clear_all_history():
    """전체 이력 삭제."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("DELETE FROM generated_predictions")
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run("server:app", host=host, port=port, reload=False)
