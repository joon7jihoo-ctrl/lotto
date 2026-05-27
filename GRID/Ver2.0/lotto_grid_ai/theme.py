"""Application stylesheet."""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication


DARK_THEME_STYLESHEET = """
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


def apply_dark_theme(app: QApplication) -> None:
    app.setStyleSheet(DARK_THEME_STYLESHEET)

