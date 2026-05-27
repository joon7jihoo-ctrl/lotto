"""Application entry point."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from .controller import LottoController
from .theme import apply_dark_theme
from .ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    window = MainWindow()
    _controller = LottoController(window)  # noqa: F841 - Qt ?? ???? ??? ?? ?? ??
    window.show()

    return app.exec()
