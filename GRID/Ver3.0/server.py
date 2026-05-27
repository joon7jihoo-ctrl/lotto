"""Lotto Grid AI Analyzer - Web App Ver3.0 (FastAPI Backend)"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).resolve().parent
VER2_DIR  = BASE_DIR.parent / "Ver 2.0"
ROOT_DIR  = BASE_DIR.parent.parent           # D:\Development\lotto
XLSX_PATH = ROOT_DIR / "lotto_history.xlsx"
DB_PATH   = BASE_DIR / "lotto_history.db"    # Ver3.0 전용 DB
STATIC_DIR = BASE_DIR / "static"

sys.path.insert(0, str(VER2_DIR))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from lotto_grid_ai.models     import AnalysisConfig
from lotto_grid_ai.storage    import LottoDataLoader
from lotto_grid_ai.analysis   import LottoAnalyzer
from lotto_grid_ai.generation import CombinationGenerator
from lotto_grid_ai.grid       import GridMapper

# ── 앱 생성 ───────────────────────────────────────────────────────────────────
app = FastAPI(title="Lotto Grid AI Ver3.0")

# ── 인메모리 분석 결과 캐시 ──────────────────────────────────────────────────
_cached_result = None
_cached_config_key: Optional[str] = None


# ── Pydantic 요청 스키마 ──────────────────────────────────────────────────────
class ConfigRequest(BaseModel):
    start_draw: int = 1
    max_draw: int = 0
    deadzone_window: int = 20
    top_candidate_count: int = 20
    output_limit: int = 30
    recent_weight: int = 55
    missing_weight: int = 25
    square_weight: int = 0
    deadzone_weight: int = 5
    mix_previous_ratio: int = 10
    max_overlap: int = 4
    max_popularity_risk: int = 3
    backtest_rounds: int = 80
    backtest_train_window: int = 120
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
            "best_hit_count":   bt.best_hit_count,
            "last_hit_count":   bt.last_hit_count,
        },
    }


def _run_analysis(req: ConfigRequest):
    global _cached_result, _cached_config_key
    key = _config_key(req)
    # start_draw/max_draw가 같으면 데이터 로드는 캐시 재사용 가능
    load_key = str((req.start_draw, req.max_draw))
    config = _to_config(req)
    loader = LottoDataLoader(xlsx_path=XLSX_PATH, db_path=DB_PATH)

    if _cached_result is not None and _cached_config_key and _cached_config_key.startswith(load_key):
        # 이미 로드된 DataFrame으로 재분석 (네트워크 없이 빠름)
        result = LottoAnalyzer().analyze(
            _cached_result.df, config,
            _cached_result.source_name, []
        )
    else:
        df, source_name, warnings = loader.load_history(config)
        result = LottoAnalyzer().analyze(df, config, source_name, warnings)

    _cached_result = result
    _cached_config_key = load_key
    return result


# ── 라우트 ────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


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
        result = _run_analysis(req)
        records, gen_warns = CombinationGenerator().generate(result, _to_config(req))
        combos = [
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
