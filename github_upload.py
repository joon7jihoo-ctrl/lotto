# -*- coding: utf-8 -*-
"""
GitHub API를 사용해 코드를 저장소에 업로드하는 스크립트.

사용법:
    python github_upload.py --token <YOUR_GITHUB_PAT>
"""

from __future__ import annotations

import argparse
import base64
import io
import sys
import time
from pathlib import Path

import requests

# Windows cp949 환경에서 UTF-8 출력을 위해 stdout 재설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO_OWNER = "joon7jihoo-ctrl"
REPO_NAME = "lotto"
BASE_DIR = Path(__file__).resolve().parent
API_BASE = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents"

# 업로드할 파일 목록 (로컬 경로 → GitHub 경로)
UPLOAD_FILES: list[tuple[Path, str]] = [
    # 루트 파일
    (BASE_DIR / "README.md",                                           "README.md"),
    (BASE_DIR / ".gitignore",                                          ".gitignore"),
    (BASE_DIR / "requirements_lotto_grid_ai.txt",                     "requirements_lotto_grid_ai.txt"),
    (BASE_DIR / "lotto_grid_ai_pyqt6.py",                             "lotto_grid_ai_pyqt6.py"),

    # Ver2.0 — 런처
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai_pyqt6_v2.py",   "GRID/Ver2.0/lotto_grid_ai_pyqt6_v2.py"),
    (BASE_DIR / "GRID" / "Ver 2.0" / "requirements_lotto_grid_ai.txt","GRID/Ver2.0/requirements_lotto_grid_ai.txt"),

    # Ver2.0 — 패키지
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai" / "__init__.py",  "GRID/Ver2.0/lotto_grid_ai/__init__.py"),
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai" / "app.py",       "GRID/Ver2.0/lotto_grid_ai/app.py"),
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai" / "models.py",    "GRID/Ver2.0/lotto_grid_ai/models.py"),
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai" / "grid.py",      "GRID/Ver2.0/lotto_grid_ai/grid.py"),
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai" / "analysis.py",  "GRID/Ver2.0/lotto_grid_ai/analysis.py"),
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai" / "generation.py","GRID/Ver2.0/lotto_grid_ai/generation.py"),
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai" / "storage.py",   "GRID/Ver2.0/lotto_grid_ai/storage.py"),
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai" / "controller.py","GRID/Ver2.0/lotto_grid_ai/controller.py"),
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai" / "ui.py",        "GRID/Ver2.0/lotto_grid_ai/ui.py"),
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai" / "theme.py",     "GRID/Ver2.0/lotto_grid_ai/theme.py"),
    (BASE_DIR / "GRID" / "Ver 2.0" / "lotto_grid_ai" / "utils.py",     "GRID/Ver2.0/lotto_grid_ai/utils.py"),

    # Ver1.0 — 패키지
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai_pyqt6.py",          "GRID/Ver1.0/lotto_grid_ai_pyqt6.py"),
    (BASE_DIR / "GRID" / "Ver1.0" / "requirements_lotto_grid_ai.txt",   "GRID/Ver1.0/requirements_lotto_grid_ai.txt"),
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai" / "__init__.py",    "GRID/Ver1.0/lotto_grid_ai/__init__.py"),
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai" / "app.py",         "GRID/Ver1.0/lotto_grid_ai/app.py"),
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai" / "models.py",      "GRID/Ver1.0/lotto_grid_ai/models.py"),
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai" / "grid.py",        "GRID/Ver1.0/lotto_grid_ai/grid.py"),
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai" / "analysis.py",    "GRID/Ver1.0/lotto_grid_ai/analysis.py"),
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai" / "generation.py",  "GRID/Ver1.0/lotto_grid_ai/generation.py"),
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai" / "storage.py",     "GRID/Ver1.0/lotto_grid_ai/storage.py"),
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai" / "controller.py",  "GRID/Ver1.0/lotto_grid_ai/controller.py"),
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai" / "ui.py",          "GRID/Ver1.0/lotto_grid_ai/ui.py"),
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai" / "theme.py",       "GRID/Ver1.0/lotto_grid_ai/theme.py"),
    (BASE_DIR / "GRID" / "Ver1.0" / "lotto_grid_ai" / "utils.py",       "GRID/Ver1.0/lotto_grid_ai/utils.py"),

    # Ver3.0 — FastAPI Web App
    (BASE_DIR / "GRID" / "Ver3.0" / "server.py",                        "GRID/Ver3.0/server.py"),
    (BASE_DIR / "GRID" / "Ver3.0" / "requirements.txt",                 "GRID/Ver3.0/requirements.txt"),
    (BASE_DIR / "GRID" / "Ver3.0" / "start.bat",                        "GRID/Ver3.0/start.bat"),
    (BASE_DIR / "GRID" / "Ver3.0" / "render.yaml",                      "GRID/Ver3.0/render.yaml"),
    (BASE_DIR / "GRID" / "Ver3.0" / "static" / "index.html",            "GRID/Ver3.0/static/index.html"),
]


def get_file_sha(session: requests.Session, github_path: str) -> str | None:
    """GitHub에 이미 해당 파일이 있으면 SHA를 반환 (업데이트 시 필요)."""
    resp = session.get(f"{API_BASE}/{github_path}")
    if resp.status_code == 200:
        return resp.json().get("sha")
    return None


def upload_file(
    session: requests.Session,
    local_path: Path,
    github_path: str,
    dry_run: bool = False,
) -> bool:
    """단일 파일을 GitHub API로 업로드 (create 또는 update)."""
    if not local_path.exists():
        print(f"  ⚠️  건너뜀 (파일 없음): {local_path}")
        return False

    content = local_path.read_bytes()
    encoded = base64.b64encode(content).decode("utf-8")
    sha = get_file_sha(session, github_path)
    action = "update" if sha else "create"

    if dry_run:
        print(f"  [DRY-RUN] {action}: {github_path}")
        return True

    payload: dict = {
        "message": f"{'chore' if action == 'update' else 'feat'}: {action} {github_path}",
        "content": encoded,
    }
    if sha:
        payload["sha"] = sha

    resp = session.put(f"{API_BASE}/{github_path}", json=payload)

    if resp.status_code in (200, 201):
        print(f"  ✅  {action}: {github_path}")
        return True
    else:
        print(f"  ❌  실패 [{resp.status_code}]: {github_path} — {resp.text[:200]}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="GitHub 저장소에 Lotto Grid AI 코드를 업로드합니다.")
    parser.add_argument("--token", required=True, help="GitHub Personal Access Token")
    parser.add_argument("--dry-run", action="store_true", help="실제 업로드 없이 대상 파일 목록만 출력")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {args.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })

    # 토큰 유효성 확인
    me = session.get("https://api.github.com/user")
    if me.status_code != 200:
        print(f"❌ GitHub 인증 실패: {me.status_code} — 토큰을 확인해 주세요.")
        return 1
    print(f"✅ 인증 성공: {me.json().get('login')}")
    print(f"📁 업로드 대상 저장소: {REPO_OWNER}/{REPO_NAME}")
    print(f"📂 로컬 기준 디렉토리: {BASE_DIR}")
    print(f"{'🔍 DRY-RUN 모드' if args.dry_run else '🚀 실제 업로드 시작'}\n")

    success = 0
    fail = 0

    for local_path, github_path in UPLOAD_FILES:
        ok = upload_file(session, local_path, github_path, dry_run=args.dry_run)
        if ok:
            success += 1
        else:
            fail += 1
        if not args.dry_run:
            time.sleep(0.3)  # GitHub API rate limit 방지

    print(f"\n{'─'*50}")
    print(f"완료: 성공 {success}개 / 실패 {fail}개")
    if fail == 0:
        print(f"🎉 https://github.com/{REPO_OWNER}/{REPO_NAME} 에서 확인하세요!")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
