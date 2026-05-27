import asyncio, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

SHOT_DIR = r"D:\Development\lotto\screenshots"

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 900})

        # ── STEP 1: 초기 화면 ─────────────────────────────────────────────
        await page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        await page.screenshot(path=SHOT_DIR + r"\01_initial.png")
        header_txt = await page.inner_text("header")
        panels = await page.query_selector_all("aside, main")
        print(f"[STEP1] 초기 화면 캡처 완료")
        print(f"  HEADER: {header_txt.strip()[:100]}")
        print(f"  PANELS: {len(panels)}개")

        # ── STEP 2: 분석 버튼 클릭 ───────────────────────────────────────
        print("[STEP2] '데이터 로드 + 백테스트 분석' 버튼 클릭")
        await page.click("#btn-analyze")

        # 로딩 오버레이 확인
        try:
            await page.wait_for_selector("#overlay", state="visible", timeout=5000)
            print("  OVERLAY: 로딩 오버레이 표시됨 ✓")
        except Exception:
            print("  OVERLAY: 오버레이를 감지하지 못함 (빠른 응답?)")

        # 분석 완료 대기
        await page.wait_for_selector("#overlay", state="hidden", timeout=120000)
        print("  ANALYSIS: 분석 완료 ✓")

        # ── STEP 3: 분석 완료 후 화면 ────────────────────────────────────
        await page.wait_for_timeout(1000)
        await page.screenshot(path=SHOT_DIR + r"\02_after_analyze.png")
        print("[STEP3] 분석 완료 화면 캡처 완료")

        # 요약 카드
        summary = await page.inner_text("#summary-card")
        print(f"  SUMMARY: {summary.strip()[:200]}")

        # 히트맵 캔버스 크기
        canvas = await page.query_selector("#heatmap-canvas")
        if canvas:
            box = await canvas.bounding_box()
            print(f"  CANVAS: width={box['width']:.0f}px height={box['height']:.0f}px")
        else:
            print("  CANVAS: 캔버스 없음!")

        # 점수표 행 수
        rows = await page.query_selector_all("#score-table-body tr")
        print(f"  SCORE_TABLE: {len(rows)}행")

        # 로그
        log_txt = await page.inner_text("#log-box")
        print(f"  LOG: {log_txt.strip()[:300]}")

        # ── STEP 4: 조합 생성 ────────────────────────────────────────────
        print("[STEP4] '관리형 번호 조합 생성' 버튼 클릭")
        await page.click("#btn-generate")

        try:
            await page.wait_for_selector("#overlay", state="visible", timeout=5000)
        except Exception:
            pass
        await page.wait_for_selector("#overlay", state="hidden", timeout=120000)
        print("  GENERATE: 완료 ✓")

        await page.wait_for_timeout(800)
        await page.screenshot(path=SHOT_DIR + r"\03_after_generate.png")
        print("[STEP5] 조합 생성 후 화면 캡처 완료")

        combo_txt = await page.inner_text("#combo-output")
        print(f"  COMBO (first 300 chars): {combo_txt.strip()[:300]}")

        await browser.close()
        print("\nDONE — 스크린샷 3장 저장 완료")

asyncio.run(run())
