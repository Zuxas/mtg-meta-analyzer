"""Install global exception + Qt message handlers so crashes leave a
forensic trail in logs/gui_crash_YYYY-MM-DD.log instead of silently
killing the process."""
import sys
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
from PyQt6.QtWidgets import QApplication, QMessageBox

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def install_handlers() -> None:
    """Call once from run_gui.py BEFORE creating QApplication."""
    sys.excepthook = _exception_hook
    qInstallMessageHandler(_qt_message_handler)


def _exception_hook(exc_type, exc_value, tb):
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / f"gui_crash_{datetime.now().strftime('%Y-%m-%d')}.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now().isoformat()} ===\n")
            traceback.print_exception(exc_type, exc_value, tb, file=f)
    except BaseException:
        # BaseException (not Exception) so KeyboardInterrupt + SystemExit
        # raised inside the formatter (Python 3.13 traceback formatter bug
        # triggered by SIGINT mid-format) don't propagate out of the crash
        # handler itself.
        pass
    # Always also print to stderr so the dev console shows it.
    try:
        traceback.print_exception(exc_type, exc_value, tb, file=sys.stderr)
    except BaseException:
        # BaseException (not Exception) so KeyboardInterrupt + SystemExit
        # raised inside the formatter (Python 3.13 traceback formatter bug
        # triggered by SIGINT mid-format) don't propagate out of the crash
        # handler itself.
        pass
    # Only surface a modal if a QApplication exists — calling QMessageBox
    # without one hard-aborts at the C++ level past any Python try/except.
    if QApplication.instance() is not None:
        try:
            body = "".join(traceback.format_exception(exc_type, exc_value, tb))
            QMessageBox.critical(None, "Unhandled exception", body[-2000:])
        except BaseException:
            pass


def _qt_message_handler(msg_type, context, message):
    if msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg,
                    QtMsgType.QtWarningMsg):
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_path = _LOG_DIR / f"qt_msgs_{datetime.now().strftime('%Y-%m-%d')}.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat()} [{msg_type}] {message}\n")
        except BaseException:
            pass
