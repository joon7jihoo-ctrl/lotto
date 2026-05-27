"""Controller and worker thread orchestration."""

from __future__ import annotations

import traceback
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from .analysis import LottoAnalyzer
from .generation import CombinationGenerator, LottoPrizeChecker
from .models import AnalysisConfig, AnalysisResult, CombinationRecord
from .storage import LottoDataLoader, LottoDatabase
from .ui import MainWindow


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
        self.checker = LottoPrizeChecker()
        self.database = LottoDatabase()

        self.current_result: Optional[AnalysisResult] = None
        self.current_source_name: str = ""
        self.current_warnings: List[str] = []
        self.current_records: List[CombinationRecord] = []

        self.thread: Optional[QThread] = None
        self.worker: Optional[AnalysisTaskWorker] = None

        self.debounce_timer = QTimer(self)
        self.debounce_timer.setInterval(250)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self._reanalyze_current_data)

        self.view.analysis_requested.connect(self.start_analysis)
        self.view.generate_requested.connect(self.generate_combinations)
        self.view.check_requested.connect(self.check_generated_numbers)
        self.view.settings_changed.connect(self._schedule_reanalysis)

    def start_analysis(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            return

        config = self.view.get_config()
        self.current_records = []
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
        self.current_records = []
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
            self.current_records = []
            self.view.show_analysis(refreshed)
            self.view.statusBar().showMessage("설정 변경 반영 완료")
        except Exception as exc:
            self.view.append_log(f"설정 반영 실패: {exc}")

    def generate_combinations(self) -> None:
        if self.current_result is None:
            self.view.show_error("데이터 없음", "먼저 '데이터 로드 + 백테스트 분석'을 실행해 주세요.")
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
            self.current_records = records
            self.view.show_combinations(records, warnings)
            try:
                saved = self.database.save_combinations(records, refreshed.latest_draw.draw_no)
                self.view.append_log(f"SQLite 조합 저장: {saved:,}개")
            except Exception as exc:
                self.view.append_log(f"SQLite 조합 저장 실패: {exc}")
            self.view.append_log(f"최종 생존 조합 {len(records):,}개 출력")
        except Exception as exc:
            self.view.show_error("조합 생성 실패", str(exc))

    def check_generated_numbers(self) -> None:
        if self.current_result is None:
            self.view.show_error("데이터 없음", "먼저 '데이터 로드 + 백테스트 분석'을 실행해 주세요.")
            return

        try:
            records = self.current_records
            if not records:
                records = self.database.load_latest_combinations()
                if records:
                    self.current_records = records
                    self.view.append_log("SQLite에서 최근 저장된 추출 번호를 불러왔습니다.")

            if not records:
                self.view.show_error("추출 번호 없음", "먼저 '관리형 번호 조합 생성'을 실행해 주세요.")
                return

            checked = self.checker.check(
                records,
                self.current_result.df,
                source_draw_no=self.current_result.latest_draw.draw_no,
            )
            self.view.show_winning_check(checked)
            self.view.append_log("추출 번호 당첨여부 확인 완료")
        except Exception as exc:
            self.view.show_error("당첨여부 확인 실패", str(exc))


