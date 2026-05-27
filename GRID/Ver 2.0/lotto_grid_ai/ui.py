"""PyQt6 widgets and the main window view."""

from __future__ import annotations

from typing import Iterable, List, Optional, Set, Tuple

import numpy as np
import seaborn as sns
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
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
from matplotlib import font_manager, rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from .grid import GridMapper
from .models import (
    GRID_SIZE,
    AnalysisConfig,
    AnalysisResult,
    CombinationRecord,
    WinningCheckRecord,
)
from .utils import format_numbers


def _configure_matplotlib_fonts() -> None:
    preferred_fonts = (
        "Malgun Gothic",
        "AppleGothic",
        "NanumGothic",
        "Noto Sans CJK KR",
        "DejaVu Sans",
    )
    available_fonts = {font.name for font in font_manager.fontManager.ttflist}
    for font_name in preferred_fonts:
        if font_name in available_fonts:
            rcParams["font.family"] = [font_name]
            break
    rcParams["axes.unicode_minus"] = False


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
        _configure_matplotlib_fonts()
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

        score_map = self._score_map(result)
        score_grid = GridMapper.numbers_to_grid(score_map, fill_value=np.nan)
        image = self._draw_heatmap(score_grid)
        self._draw_empty_cells()
        self._draw_grid_lines()
        self._draw_number_overlay(result.deadzone_numbers, "#38bdf8", "#7dd3fc", fill=True, linewidth=1.5, alpha=0.18)
        self._draw_number_overlay(result.prev_square_numbers, "#f59e0b", "#fbbf24", fill=True, linewidth=2.0, alpha=0.20)
        self._draw_number_overlay(result.final_expected_numbers, "#22c55e", "#22c55e", fill=False, linewidth=2.6, alpha=0.95)
        self._draw_labels(score_map, set(result.latest_draw.numbers))
        self._configure_axes()
        self._draw_colorbar(image)
        self.figure.tight_layout()
        self.draw_idle()

    @staticmethod
    def _score_map(result: AnalysisResult) -> dict[int, float]:
        return {
            int(row["number"]): float(row["score"])
            for _, row in result.score_table.iterrows()
        }

    def _draw_heatmap(self, score_grid: np.ndarray):
        cmap = sns.color_palette("mako", as_cmap=True)
        masked = np.ma.masked_invalid(score_grid)
        return self.ax.imshow(masked, cmap=cmap, vmin=0, vmax=100, interpolation="nearest")

    def _draw_empty_cells(self) -> None:
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                if GridMapper.pos_to_number(row, col) is not None:
                    continue
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

    def _draw_grid_lines(self) -> None:
        for edge in np.arange(-0.5, GRID_SIZE, 1):
            self.ax.axhline(edge, color="#334155", linewidth=0.8, alpha=0.85)
            self.ax.axvline(edge, color="#334155", linewidth=0.8, alpha=0.85)

    def _draw_number_overlay(
        self,
        numbers: Iterable[int],
        facecolor: str,
        edgecolor: str,
        fill: bool,
        linewidth: float,
        alpha: float,
    ) -> None:
        for number in numbers:
            row, col = GridMapper.number_to_pos(number)
            self.ax.add_patch(
                Rectangle(
                    (col - 0.5, row - 0.5),
                    1,
                    1,
                    fill=fill,
                    facecolor=facecolor if fill else "none",
                    edgecolor=edgecolor,
                    linewidth=linewidth,
                    alpha=alpha,
                )
            )

    def _draw_labels(self, score_map: dict[int, float], latest_set: Set[int]) -> None:
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

    def _configure_axes(self) -> None:
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
        self.ax.set_xlim(-0.5, GRID_SIZE - 0.5)
        self.ax.set_ylim(GRID_SIZE - 0.5, -0.5)

    def _draw_colorbar(self, image) -> None:
        cbar = self.figure.colorbar(image, ax=self.ax, fraction=0.046, pad=0.04)
        cbar.ax.tick_params(colors="#cbd5e1")
        cbar.outline.set_edgecolor("#334155")
        cbar.set_label("Composite Score", color="#cbd5e1")


class MainWindow(QMainWindow):
    """View: UI 구성과 표시만 담당합니다."""

    analysis_requested = pyqtSignal()
    generate_requested = pyqtSignal()
    check_requested = pyqtSignal()
    settings_changed = pyqtSignal()

    def __init__(self, edition_label: str = "") -> None:
        super().__init__()
        self.edition_label = edition_label.strip()
        self.setWindowTitle(self._app_title())
        self.resize(1480, 920)
        self._build_actions()
        self._build_ui()
        self._connect_setting_signals()
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("준비 완료")

    def _app_title(self) -> str:
        if self.edition_label:
            return f"Lotto Grid AI Analyzer {self.edition_label}"
        return "Lotto Grid AI Analyzer"

    def _build_actions(self) -> None:
        check_action = QAction("추출 번호 당첨여부 확인", self)
        check_action.triggered.connect(self.check_requested.emit)

        about_action = QAction("정보", self)
        about_action.triggered.connect(self._show_about)

        menubar = self.menuBar()
        verify_menu = menubar.addMenu("검증")
        verify_menu.addAction(check_action)
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

        title, subtitle = self._build_title_labels()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._build_data_group())
        layout.addWidget(self._build_weight_group())
        layout.addWidget(self._build_candidate_group())
        layout.addWidget(self._build_filter_group())
        self._add_log_box(layout)
        layout.addStretch(1)
        return panel

    def _build_title_labels(self) -> Tuple[QLabel, QLabel]:
        title = QLabel(self._app_title())
        title.setObjectName("TitleLabel")
        subtitle_text = "Backtested Combination Management Engine"
        if self.edition_label.upper() == "V2":
            subtitle_text = "V2 Resilient Local-First Engine"
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("SubtitleLabel")
        return title, subtitle

    def _build_data_group(self) -> QGroupBox:
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

        self.load_button = QPushButton("데이터 로드 + 백테스트 분석")
        self.load_button.setObjectName("PrimaryButton")
        self.load_button.clicked.connect(self.analysis_requested.emit)
        data_layout.addWidget(self.load_button, 2, 0, 1, 2)
        return data_group

    def _build_weight_group(self) -> QGroupBox:
        weight_group = QGroupBox("Layer 2~5 · 예상수 가중치")
        weight_layout = QVBoxLayout(weight_group)

        self.recent_weight = SliderSpinBox("시계열 빈도 가중치", 0, 100, 55)
        self.missing_weight = SliderSpinBox("장기 미출수 가중치", 0, 100, 25)
        self.square_weight = SliderSpinBox("직전사각수 가중치", 0, 100, 0)
        self.deadzone_weight = SliderSpinBox("완전사각/데드존 가중치", 0, 100, 5)

        weight_layout.addWidget(self.recent_weight)
        weight_layout.addWidget(self.missing_weight)
        weight_layout.addWidget(self.square_weight)
        weight_layout.addWidget(self.deadzone_weight)
        return weight_group

    def _build_candidate_group(self) -> QGroupBox:
        candidate_group = QGroupBox("Layer 6~8 · 후보/검증 설정")
        candidate_layout = QGridLayout(candidate_group)

        self.deadzone_window_spin = self._spinbox(1, 200, 20, " 회")
        self.top_candidate_spin = self._spinbox(6, 45, 20, " 개")
        self.output_limit_spin = self._spinbox(1, 300, 30, " 조합")
        self.mix_ratio = SliderSpinBox("이전당첨 믹스 비율", 0, 100, 10, "%")
        self.max_overlap_spin = self._spinbox(0, 5, 4, " 개")
        self.pattern_risk_spin = self._spinbox(0, 10, 3, " 점")
        self.backtest_rounds_spin = self._spinbox(0, 300, 80, " 회")

        candidate_layout.addWidget(QLabel("데드존 추적 N"), 0, 0)
        candidate_layout.addWidget(self.deadzone_window_spin, 0, 1)
        candidate_layout.addWidget(QLabel("핵심 예상수 N"), 1, 0)
        candidate_layout.addWidget(self.top_candidate_spin, 1, 1)
        candidate_layout.addWidget(QLabel("출력 조합 수"), 2, 0)
        candidate_layout.addWidget(self.output_limit_spin, 2, 1)
        candidate_layout.addWidget(self.mix_ratio, 3, 0, 1, 2)
        candidate_layout.addWidget(QLabel("조합 간 최대 중복"), 4, 0)
        candidate_layout.addWidget(self.max_overlap_spin, 4, 1)
        candidate_layout.addWidget(QLabel("인기패턴 위험 최대"), 5, 0)
        candidate_layout.addWidget(self.pattern_risk_spin, 5, 1)
        candidate_layout.addWidget(QLabel("백테스트 회차"), 6, 0)
        candidate_layout.addWidget(self.backtest_rounds_spin, 6, 1)

        self.generate_button = QPushButton("관리형 번호 조합 생성")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.clicked.connect(self.generate_requested.emit)
        candidate_layout.addWidget(self.generate_button, 7, 0, 1, 2)
        return candidate_group

    @staticmethod
    def _spinbox(minimum: int, maximum: int, value: int, suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        if suffix:
            spin.setSuffix(suffix)
        return spin

    def _build_filter_group(self) -> QGroupBox:
        filter_group = QGroupBox("Layer 8~10 · 조합 관리 필터")
        filter_layout = QVBoxLayout(filter_group)
        filter_text = QLabel(
            "· 총합: 100~170\n"
            "· 홀짝: 홀수 2~4개\n"
            "· 고저: 고번호(23~45) 2~4개\n"
            "· AC값: 7 이상\n"
            "· 생일수/연속수/끝수 몰림 회피\n"
            "· 생성 기준 회차 이후만 당첨 검증"
        )
        filter_text.setObjectName("HintLabel")
        filter_layout.addWidget(filter_text)
        return filter_group

    def _add_log_box(self, layout: QVBoxLayout) -> None:
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(140)
        self.log_box.setObjectName("LogBox")
        layout.addWidget(QLabel("진행 로그"))
        layout.addWidget(self.log_box)

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

        combos_title = QLabel("Layer 8~10 관리형 최종 조합")
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
            self.max_overlap_spin,
            self.pattern_risk_spin,
            self.backtest_rounds_spin,
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
            max_overlap=int(self.max_overlap_spin.value()),
            max_popularity_risk=int(self.pattern_risk_spin.value()),
            backtest_rounds=int(self.backtest_rounds_spin.value()),
        )

    def set_busy(self, busy: bool) -> None:
        self.load_button.setEnabled(not busy)
        self.generate_button.setEnabled(not busy)
        if busy:
            self.statusBar().showMessage("분석 실행 중...")
            self.load_button.setText("분석 중...")
        else:
            self.statusBar().showMessage("준비 완료")
            self.load_button.setText("데이터 로드 + 백테스트 분석")

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
        backtest = result.backtest_summary
        if backtest.rounds:
            backtest_text = (
                f"\n백테스트 후보군 적중: 평균 {backtest.avg_hits:.2f}개 "
                f"(무작위 기대 {backtest.random_avg_hits:.2f}) · "
                f"3개 이상 {backtest.hit3_rate * 100:.1f}% "
                f"(무작위 {backtest.random_hit3_rate * 100:.1f}%)"
            )
        else:
            backtest_text = "\n백테스트: 데이터 부족 또는 비활성화"

        self.summary_card.setText(
            f"데이터 소스: {result.source_name}\n"
            f"분석 회차 수: {len(result.df):,}회 · 최신 회차: {latest.draw_no}회 ({latest.draw_date})\n"
            f"직전 당첨: {format_numbers(latest.numbers)} · 보너스: {latest.bonus if latest.bonus is not None else '-'}\n"
            f"핵심 예상수: {format_numbers(result.final_expected_numbers)}\n"
            f"조합 후보군: {format_numbers(result.candidate_pool)}"
            f"{backtest_text}"
            f"{warning_text}"
        )

        self.heatmap.render(result)
        self._fill_score_table(result)
        self.combo_output.setPlainText("상단의 '관리형 번호 조합 생성' 버튼을 누르면 다양성/패턴 필터를 통과한 조합이 표시됩니다.")

    def show_combinations(self, records: List[CombinationRecord], warnings: Optional[List[str]] = None) -> None:
        if not records:
            self.combo_output.setPlainText("조건을 만족하는 조합을 찾지 못했습니다. 후보수 N 또는 믹스 비율을 조정해 보세요.")
            return

        lines: List[str] = []
        if warnings:
            for warning in warnings:
                lines.append(f"[주의] {warning}")
            lines.append("")

        lines.append("순위 | 번호 조합                 | 총합 | 홀 | 고 | AC | 이월 | 패턴 | 점수")
        lines.append("-" * 88)

        for idx, record in enumerate(records, 1):
            combo = " ".join(f"{n:02d}" for n in record.numbers)
            pattern = f"{record.pattern_risk}"
            if record.pattern_notes:
                pattern += f"({record.pattern_notes})"
            lines.append(
                f"{idx:>3} | {combo:<23} | "
                f"{record.total:>3} | {record.odd_count:>1} | {record.high_count:>1} | "
                f"{record.ac_value:>2} | {record.carry_count:>2} | {pattern:<12} | {record.score:>7.2f}"
            )

        self.combo_output.setPlainText("\n".join(lines))

    def show_winning_check(self, records: List[WinningCheckRecord]) -> None:
        if not records:
            self.combo_output.setPlainText("확인할 추출 번호가 없습니다.")
            return

        lines = [
            "순위 | 추출 번호                  | 결과 | 일치 | 보너스 | 생성기준 | 확인 회차",
            "-" * 96,
        ]

        for idx, record in enumerate(records, 1):
            combo = format_numbers(record.numbers)
            matched = format_numbers(record.matched_numbers) if record.matched_numbers else "-"
            draw_info = "-"
            if record.draw_no is not None:
                draw_info = f"{record.draw_no}회"
                if record.draw_date:
                    draw_info += f" ({record.draw_date})"
            bonus = "Y" if record.bonus_match else ""
            source_info = f"{record.source_draw_no}회 이후" if record.source_draw_no is not None else "전체"
            lines.append(
                f"{idx:>3} | {combo:<27} | {record.rank:<3} | "
                f"{matched:<17} | {bonus:^6} | {source_info:<10} | {draw_info}"
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
            f"{self._app_title()}\n\n"
            "백테스트 가능한 후보군 분석과 조합 다양성 관리를 적용한 PyQt6 예제입니다.\n"
            "로또 추첨은 독립 무작위 사건이며, 본 도구는 당첨을 보장하지 않습니다.",
        )


