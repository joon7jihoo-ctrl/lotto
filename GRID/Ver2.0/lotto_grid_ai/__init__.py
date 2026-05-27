"""Lotto Grid AI Analyzer package."""

try:
    from .app import main
    __all__ = ["main"]
except ImportError:
    # GUI 라이브러리(PyQt6) 없는 서버 환경에서는 무시
    __all__ = []
