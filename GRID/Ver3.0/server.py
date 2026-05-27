"""Lotto Grid AI Analyzer - Web App Ver3.0 (FastAPI Backend)"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

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

# ── 앱 생성 ───────────────────────────────────────────────────────────────────
app = FastAPI(title="로또번호 랜덤 생성")

# ── Static 파일 서빙 ──────────────────────────────────────────────────────────
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── 인메모리 분석 결과 캐시 ──────────────────────────────────────────────────
_cached_result = None
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
    # 토요일 = weekday 5
    days_ahead = (5 - from_dt.weekday()) % 7
    if days_ahead == 0:
        # 오늘이 토요일이면 20:45 이후인 경우 다음 주로
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


@app.get("/api/info")
def get_info():
    """최신 회차 정보 + 다음 추첨 일정 반환 (분석 없이 빠른 응답)."""
    try:
        loader = LottoDataLoader(xlsx_path=XLSX_PATH, db_path=DB_PATH)
        config = AnalysisConfig(start_draw=1, max_draw=0)
        df, source_name, _ = loader.load_history(config)
        if df is None or df.empty:
            return JSONResponse({"status": "error", "message": "데이터 없음"}, 500)

        latest = df.iloc[-1]
        latest_no   = int(latest["draw_no"])
        latest_date = str(latest.get("date", ""))
        numbers     = [int(latest[f"n{i}"]) for i in range(1, 7)]
        bonus_raw   = latest.get("bonus", None)
        bonus       = int(bonus_raw) if bonus_raw is not None and pd.notna(bonus_raw) else None

        # 다음 토요일 계산 (KST 기준, 서버가 UTC라면 +9)
        try:
            import pytz  # type: ignore
            kst  = pytz.timezone("Asia/Seoul")
            now  = datetime.now(kst)
        except ImportError:
            now  = datetime.utcnow() + timedelta(hours=9)

        next_sat = _next_saturday(now)
        next_no  = latest_no + 1

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
        return {
            "status":           "ok",
            "combinations":     combos,
            "warnings":         gen_warns,
            "data":             _serialize_result(result),
        }
    except Exception as exc:
        import traceback
        return JSONResponse(
            {"status": "error", "message": str(exc), "trace": traceback.format_exc()},
            status_code=500,
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run("server:app", host=host, port=port, reload=False)
