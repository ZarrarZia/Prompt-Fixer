"""
Prompt Fixer - floating desktop overlay that rewrites the text in the active
input field using a local Ollama model.

  * Left click            -> transform the focused input in place
  * Hold 3 seconds        -> mode menu (Standard Structured / Loop Engineering)
  * Right click           -> same menu, instantly
  * Drag                  -> move the widget (position is remembered)

Pipeline (Windows):
  The overlay never takes keyboard focus (WS_EX_NOACTIVATE), and a background
  tracker remembers the last foreground window that is not ours. On click, that
  window is re-foregrounded (AttachThreadInput + SetForegroundWindow), then
  Ctrl+A / Ctrl+C are injected with SendInput, the text is sent to Ollama on a
  worker thread, and the result is pasted back with Ctrl+A / Ctrl+V.

Requirements:  pip install PyQt6      (Ollama running on localhost:11434)
Config (env):  PROMPT_FIXER_MODEL (default qwen2.5-coder:1.5b), OLLAMA_HOST
Headless test: python app.py --test "make a login page"  [--loop]
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from PyQt6.QtCore import (
    QObject, QPoint, QPointF, QRectF, QRunnable, QSettings, Qt, QThreadPool,
    QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QActionGroup, QBrush, QColor, QConicalGradient, QFont, QGuiApplication,
    QMouseEvent, QPainter, QPen, QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QMenu, QToolTip, QWidget

IS_WINDOWS = sys.platform == "win32"


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
APP_NAME = "PromptFixer"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
if not OLLAMA_HOST.startswith("http"):
    OLLAMA_HOST = "http://" + OLLAMA_HOST
OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
OLLAMA_TAGS_URL = f"{OLLAMA_HOST}/api/tags"
DEFAULT_MODEL = os.environ.get("PROMPT_FIXER_MODEL", "qwen2.5-coder:1.5b")

OLLAMA_OPTIONS = {
    "num_ctx": 2048,        # small KV cache -> low RAM/VRAM, fast decode
    "temperature": 0.2,     # near-deterministic rewrites
    "num_predict": 512,     # hard cap on output tokens
}
KEEP_ALIVE = -1             # keep the model resident forever (no cold starts)

HOLD_MS = 3000              # long-press duration for the mode menu
HEALTH_TIMEOUT_S = 1.5
INFERENCE_TIMEOUT_S = 180   # first call after boot may include model load
HEALTH_POLL_MS = 15000
FOCUS_TRACK_MS = 150
CLIPBOARD_WAIT_MS = 800

WIDGET_SIZE = 68
DISC_RADIUS = 22

MODE_STANDARD = "standard"
MODE_LOOP = "loop"

SYSTEM_PROMPTS = {
    MODE_STANDARD: (
        "You are an expert prompt engineer. Transform the user's raw instruction "
        "into a crisp, high-signal prompt.\n"
        "Structure:\n"
        "- [ROLE & CONTEXT]: Specific role and scope.\n"
        "- [TASK]: Clear, unambiguous objective.\n"
        "- [CONSTRAINTS]: Technical boundaries, format, and edge cases.\n"
        "Output ONLY the transformed prompt without preamble."
    ),
    MODE_LOOP: (
        "You are an autonomous agent prompt architect. Convert the raw instruction "
        "into a closed-loop execution protocol.\n"
        "Structure:\n"
        "- [GOAL]: Precise deliverable.\n"
        "- [PHASE 1 - INSPECTION & HYPOTHESIS]: Inspect existing codebase/state "
        "without making changes.\n"
        "- [PHASE 2 - INCREMENTAL DIFF]: Minimal, isolated code changes.\n"
        "- [PHASE 3 - VERIFICATION]: Exact command-line tests or validation scripts.\n"
        "- [PHASE 4 - SELF-CORRECTION]: Rollback and triage conditions if tests fail.\n"
        "- [TERMINATION CRITERIA]: Exact conditions when the agent can mark the "
        "task complete.\n"
        "Output ONLY the structured prompt without preamble."
    ),
}

# Output tokens dominate latency on CPU; this line cuts them ~40% with no
# loss of structure. Set to "" for the longer, more verbose rewrites.
BREVITY = ("\nBe terse: each section is 1-2 short lines or a few bullet fragments. "
           "No filler words, no repetition of the input.")

# Initial guess of output length per mode (tokens), refined by a running
# average of real runs; drives the progress percentage.
EXPECTED_TOKENS = {"standard": 60, "loop": 140}


@dataclass(frozen=True)
class ModeStyle:
    label: str
    badge: str
    primary: QColor
    secondary: QColor


MODE_STYLES = {
    MODE_STANDARD: ModeStyle("Standard Structured", "S", QColor("#22c55e"), QColor("#3b82f6")),
    MODE_LOOP: ModeStyle("Loop Engineering", "L", QColor("#a855f7"), QColor("#f59e0b")),
}
COLOR_ERROR = QColor("#ef4444")
COLOR_SUCCESS = QColor("#4ade80")
COLOR_PROGRESS = QColor("#22c55e")
COLOR_TRACK = QColor(17, 24, 39, 220)


# --------------------------------------------------------------------------- #
# Ollama client (pure stdlib, called only from worker threads)
# --------------------------------------------------------------------------- #
class OllamaError(Exception):
    pass


def _http_json(url: str, payload: dict | None, timeout: float) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data else "GET",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except ValueError:
            pass
        raise OllamaError(f"Ollama HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise OllamaError(f"Ollama is offline or unreachable at {OLLAMA_HOST}") from e


def ollama_list_models() -> list[str]:
    return [m["name"] for m in _http_json(OLLAMA_TAGS_URL, None, HEALTH_TIMEOUT_S).get("models", [])]


def ollama_warm(model: str) -> None:
    """Load the model into memory (empty message list = load only) and pin it."""
    _http_json(OLLAMA_CHAT_URL, {
        "model": model, "messages": [], "keep_alive": KEEP_ALIVE,
        "options": OLLAMA_OPTIONS,
    }, INFERENCE_TIMEOUT_S)


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[\w-]*\n(.*?)\n```$", re.DOTALL)


def clean_output(text: str) -> str:
    text = _THINK_RE.sub("", text).strip()
    m = _FENCE_RE.match(text)
    return (m.group(1) if m else text).strip()


def ollama_unload(model: str) -> None:
    _http_json(OLLAMA_CHAT_URL, {"model": model, "messages": [], "keep_alive": 0}, HEALTH_TIMEOUT_S * 4)


def ollama_transform(model: str, mode: str, raw: str, progress=None) -> tuple[str, int]:
    """Streamed chat call. `progress(tokens_so_far)` fires per generated token.
    Returns (cleaned text, output token count)."""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPTS[mode] + BREVITY},
            {"role": "user", "content": raw},
        ],
        "stream": True,
        "keep_alive": KEEP_ALIVE,
        "options": OLLAMA_OPTIONS,
    }).encode()
    req = urllib.request.Request(OLLAMA_CHAT_URL, data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    parts: list[str] = []
    tokens = 0
    try:
        with urllib.request.urlopen(req, timeout=INFERENCE_TIMEOUT_S) as resp:
            for line in resp:
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise OllamaError(f"Ollama: {chunk['error']}")
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    parts.append(piece)
                    tokens += 1
                    if progress:
                        progress(tokens)
                if chunk.get("done"):
                    tokens = chunk.get("eval_count", tokens)
                    break
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except ValueError:
            pass
        raise OllamaError(f"Ollama HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise OllamaError(f"Ollama is offline or unreachable at {OLLAMA_HOST}") from e
    out = clean_output("".join(parts))
    if not out:
        raise OllamaError("Model returned an empty response")
    return out, tokens


# --------------------------------------------------------------------------- #
# Background workers (QThreadPool) - GUI thread never blocks on I/O
# --------------------------------------------------------------------------- #
class WorkerSignals(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int)


class Worker(QRunnable):
    def __init__(self, fn, *args, report_progress: bool = False):
        super().__init__()
        self.fn, self.args = fn, args
        self.report_progress = report_progress
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            if self.report_progress:
                result = self.fn(*self.args, progress=self.signals.progress.emit)
            else:
                result = self.fn(*self.args)
        except OllamaError as e:
            self.signals.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 - surface anything to the UI
            self.signals.failed.emit(f"{type(e).__name__}: {e}")
        else:
            self.signals.succeeded.emit(result)


# --------------------------------------------------------------------------- #
# Win32 layer: focus tracking/restoration + synthetic keystrokes
# --------------------------------------------------------------------------- #
class Win32:
    available = False

    def __init__(self) -> None:
        if not IS_WINDOWS:
            return
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u32, self.k32 = u32, k32
        HWND, DWORD, BOOL, UINT = wintypes.HWND, wintypes.DWORD, wintypes.BOOL, wintypes.UINT
        ULONG_PTR = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]

        class MOUSEINPUT(ctypes.Structure):  # only present to size the union
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", DWORD),
                        ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", DWORD), ("u", _U)]

        self.INPUT, self.KEYBDINPUT = INPUT, KEYBDINPUT

        def sig(fn, res, *args):
            fn.restype, fn.argtypes = res, list(args)

        sig(u32.GetForegroundWindow, HWND)
        sig(u32.SetForegroundWindow, BOOL, HWND)
        sig(u32.BringWindowToTop, BOOL, HWND)
        sig(u32.IsWindow, BOOL, HWND)
        sig(u32.IsIconic, BOOL, HWND)
        sig(u32.ShowWindow, BOOL, HWND, ctypes.c_int)
        sig(u32.GetAncestor, HWND, HWND, UINT)
        sig(u32.GetWindowThreadProcessId, DWORD, HWND, ctypes.POINTER(DWORD))
        sig(u32.AttachThreadInput, BOOL, DWORD, DWORD, BOOL)
        sig(u32.SendInput, UINT, UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        sig(u32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
        sig(u32.GetClipboardSequenceNumber, DWORD)
        sig(k32.GetCurrentThreadId, DWORD)
        self._get_style = getattr(u32, "GetWindowLongPtrW", u32.GetWindowLongW)
        self._set_style = getattr(u32, "SetWindowLongPtrW", u32.SetWindowLongW)
        sig(self._get_style, ctypes.c_ssize_t, HWND, ctypes.c_int)
        sig(self._set_style, ctypes.c_ssize_t, HWND, ctypes.c_int, ctypes.c_ssize_t)
        self.pid = os.getpid()
        self.available = True

    # -- window helpers ----------------------------------------------------- #
    def make_non_activating(self, hwnd: int) -> None:
        GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x80
        style = self._get_style(hwnd, GWL_EXSTYLE)
        self._set_style(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)

    def foreign_foreground(self) -> int | None:
        """Top-level foreground window if it belongs to another process."""
        hwnd = self.u32.GetForegroundWindow()
        if not hwnd:
            return None
        hwnd = self.u32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
        pid = self.wt.DWORD()
        self.u32.GetWindowThreadProcessId(hwnd, self.ct.byref(pid))
        return None if pid.value == self.pid else hwnd

    def is_foreground(self, hwnd: int) -> bool:
        fg = self.u32.GetForegroundWindow()
        return bool(fg) and (fg == hwnd or self.u32.GetAncestor(fg, 2) == hwnd)

    def focus(self, hwnd: int) -> bool:
        u32 = self.u32
        if not hwnd or not u32.IsWindow(hwnd):
            return False
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        if self.is_foreground(hwnd):
            return True
        # Join input queues so Windows' foreground-lock rules allow the switch.
        me = self.k32.GetCurrentThreadId()
        fg = u32.GetForegroundWindow()
        fg_tid = u32.GetWindowThreadProcessId(fg, None) if fg else 0
        tgt_tid = u32.GetWindowThreadProcessId(hwnd, None)
        attached = [t for t in {fg_tid, tgt_tid} if t and t != me and u32.AttachThreadInput(me, t, True)]
        try:
            u32.BringWindowToTop(hwnd)
            u32.SetForegroundWindow(hwnd)
        finally:
            for t in attached:
                u32.AttachThreadInput(me, t, False)
        if self._settle(hwnd):
            return True
        # Last resort: a synthetic Alt tap unlocks SetForegroundWindow.
        self._send([(0x12, False), (0x12, True)])
        u32.SetForegroundWindow(hwnd)
        return self._settle(hwnd)

    def _settle(self, hwnd: int, timeout_s: float = 0.15) -> bool:
        # Foreground changes land asynchronously in the target's thread.
        deadline = time.monotonic() + timeout_s
        while not self.is_foreground(hwnd):
            if time.monotonic() > deadline:
                return False
            time.sleep(0.01)
        return True

    # -- keyboard ----------------------------------------------------------- #
    def _send(self, keys: list[tuple[int, bool]]) -> None:
        KEYEVENTF_KEYUP = 0x2
        arr = (self.INPUT * len(keys))()
        for i, (vk, up) in enumerate(keys):
            arr[i].type = 1  # INPUT_KEYBOARD
            arr[i].ki = self.KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
        self.u32.SendInput(len(keys), arr, self.ct.sizeof(self.INPUT))

    def ctrl_chord(self, vk: int) -> None:
        # Release any physically held modifiers so they don't corrupt the chord.
        held = [m for m in (0x10, 0x12, 0x5B, 0x5C) if self.u32.GetAsyncKeyState(m) & 0x8000]
        self._send([(m, True) for m in held]
                   + [(0x11, False), (vk, False), (vk, True), (0x11, True)])

    def clipboard_seq(self) -> int:
        return int(self.u32.GetClipboardSequenceNumber())


VK_A, VK_C, VK_V = 0x41, 0x43, 0x56


# --------------------------------------------------------------------------- #
# Progress pill - green bar + percentage shown beside the overlay while busy
# --------------------------------------------------------------------------- #
class ProgressPill(QWidget):
    W, H = 168, 34

    def __init__(self, win: Win32) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(self.W, self.H)
        self.win = win
        self.percent = 0.0
        self.label = "Rewriting"

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self.win.available:
            self.win.make_non_activating(int(self.winId()))

    def place_beside(self, anchor: QWidget) -> None:
        geo = anchor.frameGeometry()
        screen = anchor.screen().availableGeometry()
        x = geo.left() - self.W - 4                       # prefer left of the overlay
        if x < screen.left():
            x = geo.right() + 4
        y = geo.center().y() - self.H // 2
        self.move(x, max(screen.top(), min(y, screen.bottom() - self.H)))

    def set_progress(self, percent: float, label: str) -> None:
        self.percent, self.label = percent, label
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(0.5, 0.5, self.W - 1, self.H - 1)
        p.setPen(QPen(QColor(55, 65, 81), 1.0))
        p.setBrush(QColor(17, 24, 39, 240))
        p.drawRoundedRect(body, self.H / 2, self.H / 2)

        # Text row: label left, percentage right
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        p.setPen(QColor("#e5e7eb"))
        text_rect = QRectF(14, 4, self.W - 28, 16)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.label)
        p.setPen(COLOR_PROGRESS)
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        p.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"{int(round(self.percent))}%")

        # Bar: track + green fill
        bar = QRectF(14, 22, self.W - 28, 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(55, 65, 81))
        p.drawRoundedRect(bar, 2.5, 2.5)
        fill = QRectF(bar.x(), bar.y(), max(bar.height(), bar.width() * self.percent / 100), bar.height())
        p.setBrush(COLOR_PROGRESS)
        p.drawRoundedRect(fill, 2.5, 2.5)
        p.end()


# --------------------------------------------------------------------------- #
# Overlay widget
# --------------------------------------------------------------------------- #
class OverlayWidget(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(WIDGET_SIZE, WIDGET_SIZE)
        self.setMouseTracking(True)

        self.settings = QSettings(APP_NAME, APP_NAME)
        self.mode = self.settings.value("mode", MODE_STANDARD)
        if self.mode not in MODE_STYLES:
            self.mode = MODE_STANDARD
        self.model = os.environ.get("PROMPT_FIXER_MODEL") or self.settings.value("model", DEFAULT_MODEL)

        self.win = Win32()
        self.pill = ProgressPill(self.win)
        self.pool = QThreadPool.globalInstance()
        self._workers: set[Worker] = set()   # keep runnables' signals alive

        # state
        self.online: bool | None = None
        self.models: list[str] = []
        self.warmed_model: str | None = None
        self.busy = False
        self.target_hwnd: int | None = None
        self.job_target: int | None = None
        self.saved_clip = None
        self.hover = False
        self.flash_color: QColor | None = None
        # progress: target is set by pipeline events, shown eases toward it
        self.progress_target = 0.0
        self.progress_shown = 0.0
        self.waiting_first_token = False
        self.expected_tokens = 0

        # press / drag / hold
        self.pressing = False
        self.dragging = False
        self.press_global = QPoint()
        self.press_win = QPoint()
        self.press_t = 0.0
        self.hold_progress = 0.0

        self.hold_timer = QTimer(self, singleShot=True, interval=HOLD_MS, timeout=self._on_hold_complete)
        self.anim_timer = QTimer(self, interval=16, timeout=self._on_anim_tick)
        self.flash_timer = QTimer(self, singleShot=True, timeout=self._clear_flash)
        self.health_timer = QTimer(self, interval=HEALTH_POLL_MS, timeout=self.check_health)
        self.track_timer = QTimer(self, interval=FOCUS_TRACK_MS, timeout=self._track_foreground)

        self._restore_position()
        self._update_tooltip()
        self.health_timer.start()
        if self.win.available:
            self.track_timer.start()
        QTimer.singleShot(0, self.check_health)

    # ------------------------------------------------------------------ setup
    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self.win.available:
            self.win.make_non_activating(int(self.winId()))

    def _restore_position(self) -> None:
        pos = self.settings.value("pos")
        screen = QGuiApplication.primaryScreen().availableGeometry()
        if isinstance(pos, QPoint) and any(
                s.availableGeometry().contains(pos + QPoint(WIDGET_SIZE // 2, WIDGET_SIZE // 2))
                for s in QGuiApplication.screens()):
            self.move(pos)
        else:
            self.move(screen.right() - WIDGET_SIZE - 24, screen.bottom() - WIDGET_SIZE - 96)

    def _update_tooltip(self) -> None:
        status = {None: "checking...", True: "online", False: "OFFLINE"}[self.online]
        self.setToolTip(f"Prompt Fixer - {MODE_STYLES[self.mode].label} mode\n"
                        f"Model: {self.model} (Ollama {status})\n"
                        "Click: transform  |  Hold 3s / right-click: menu")

    # --------------------------------------------------------------- workers
    def _run(self, fn, *args, ok=None, fail=None, progress=None) -> None:
        w = Worker(fn, *args, report_progress=progress is not None)
        if progress:
            w.signals.progress.connect(progress)
        self._workers.add(w)
        w.setAutoDelete(False)

        def done(*_):
            self._workers.discard(w)
        if ok:
            w.signals.succeeded.connect(ok)
        if fail:
            w.signals.failed.connect(fail)
        w.signals.succeeded.connect(done)
        w.signals.failed.connect(done)
        self.pool.start(w)

    def check_health(self) -> None:
        self._run(ollama_list_models, ok=self._on_health_ok, fail=self._on_health_fail)

    def _on_health_ok(self, models: list[str]) -> None:
        self.online, self.models = True, models
        self._update_tooltip()
        self.update()
        if self.warmed_model != self.model and (self.model in models or f"{self.model}:latest" in models):
            self.warmed_model = self.model  # optimistic; reset on failure
            self._run(ollama_warm, self.model, fail=self._on_warm_fail)

    def _on_health_fail(self, _msg: str) -> None:
        self.online, self.warmed_model = False, None
        self._update_tooltip()
        self.update()

    def _on_warm_fail(self, _msg: str) -> None:
        self.warmed_model = None

    # --------------------------------------------------------- focus tracking
    def _track_foreground(self) -> None:
        hwnd = self.win.foreign_foreground()
        if hwnd:
            self.target_hwnd = hwnd

    # ------------------------------------------------------------ mouse input
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.RightButton:
            self.open_mode_selection_menu()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.pressing, self.dragging = True, False
        self.press_global = e.globalPosition().toPoint()
        self.press_win = self.pos()
        self.press_t = time.monotonic()
        self.hold_progress = 0.0
        self.hold_timer.start()
        self.anim_timer.start()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if not self.pressing:
            return
        delta = e.globalPosition().toPoint() - self.press_global
        if not self.dragging and delta.manhattanLength() >= QApplication.startDragDistance():
            self.dragging = True
            self.hold_timer.stop()
            self.hold_progress = 0.0
        if self.dragging:
            self.move(self.press_win + delta)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self.pressing:
            return
        was_drag = self.dragging
        self._reset_press()
        if was_drag:
            self.settings.setValue("pos", self.pos())
        else:
            self.execute_prompt_transformation()

    def _reset_press(self) -> None:
        self.pressing = self.dragging = False
        self.hold_timer.stop()
        self.hold_progress = 0.0
        self._sync_anim()
        self.update()

    def _on_hold_complete(self) -> None:
        if self.pressing and not self.dragging:
            self._reset_press()     # consume the press: release must not transform
            self.open_mode_selection_menu()

    def enterEvent(self, e) -> None:
        self.hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self.hover = False
        self.update()

    # ------------------------------------------------------------------ menu
    def open_mode_selection_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#111827;color:#e5e7eb;border:1px solid #374151;"
            "border-radius:8px;padding:6px}"
            "QMenu::item{padding:6px 18px;border-radius:4px}"
            "QMenu::item:selected{background:#1f2937}"
            "QMenu::item:disabled{color:#6b7280}"
            "QMenu::separator{height:1px;background:#374151;margin:4px 8px}")

        group = QActionGroup(menu)
        for key, style in MODE_STYLES.items():
            dot = "●"
            act = QAction(f"{dot}  {style.label} Prompt", menu, checkable=True)
            act.setChecked(key == self.mode)
            act.triggered.connect(lambda _=False, k=key: self.set_mode(k))
            group.addAction(act)
            menu.addAction(act)

        menu.addSeparator()
        model_menu = menu.addMenu(f"Model: {self.model}")
        if self.models:
            mgroup = QActionGroup(model_menu)
            for name in self.models:
                act = QAction(name, model_menu, checkable=True)
                act.setChecked(name == self.model)
                act.triggered.connect(lambda _=False, n=name: self.set_model(n))
                mgroup.addAction(act)
                model_menu.addAction(act)
        else:
            model_menu.addAction("(Ollama offline - no models)").setEnabled(False)

        status = {None: "checking...", True: "online", False: "offline"}[self.online]
        menu.addAction(f"Ollama: {status}").setEnabled(False)
        menu.addAction("Recheck connection", self.check_health)
        menu.addSeparator()
        menu.addAction("Quit", QApplication.quit)

        # Popup beside the widget, kept on-screen.
        hint = menu.sizeHint()
        geo = self.screen().availableGeometry()
        p = self.mapToGlobal(QPoint(-hint.width() - 6, 0))
        if p.x() < geo.left():
            p.setX(self.mapToGlobal(QPoint(WIDGET_SIZE + 6, 0)).x())
        p.setY(max(geo.top(), min(p.y(), geo.bottom() - hint.height())))
        menu.popup(p)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.settings.setValue("mode", mode)
        self._update_tooltip()
        self.flash(MODE_STYLES[mode].primary, 400)
        self._show_tip(f"{MODE_STYLES[mode].label} mode")

    def set_model(self, name: str) -> None:
        if name != self.model and self.warmed_model:
            self._run(ollama_unload, self.warmed_model)   # free its RAM
        self.warmed_model = None
        self.model = name
        self.settings.setValue("model", name)
        self._update_tooltip()
        self.check_health()   # triggers warm-up of the new model

    # ------------------------------------------------- transformation pipeline
    def execute_prompt_transformation(self) -> None:
        if self.busy:
            return
        if not self.win.available:
            return self._fail("Focus restoration and key injection require Windows.")
        if not self.target_hwnd or not self.win.u32.IsWindow(self.target_hwnd):
            return self._fail("No target window. Click into your editor first, then the overlay.")
        self.busy = True
        self.job_target = self.target_hwnd
        self.progress_shown, self.progress_target = 0.0, 3.0
        self.waiting_first_token = False
        self._show_progress()
        self._sync_anim()
        # Step 1: verify Ollama BEFORE touching the clipboard or the target.
        self._run(ollama_list_models, ok=self._on_preflight_ok, fail=self._on_preflight_fail)

    def _on_preflight_fail(self, msg: str) -> None:
        self._on_health_fail(msg)
        self._fail(msg)

    def _on_preflight_ok(self, models: list[str]) -> None:
        self._on_health_ok(models)
        if self.model not in models and f"{self.model}:latest" not in models:
            return self._fail(f"Model '{self.model}' is not pulled. Run: ollama pull {self.model}")
        # Step 2: snapshot clipboard, refocus target, select-all + copy.
        self.progress_target = 6.0
        self.saved_clip = self._snapshot_clipboard()
        if not self.win.focus(self.job_target):
            return self._fail("Could not return focus to the target window.")
        QTimer.singleShot(60, self._select_and_copy)

    def _select_and_copy(self) -> None:
        self.win.ctrl_chord(VK_A)
        seq = self.win.clipboard_seq()
        QTimer.singleShot(40, lambda: (self.win.ctrl_chord(VK_C),
                                       self._await_clipboard(seq, time.monotonic())))

    def _await_clipboard(self, seq: int, t0: float) -> None:
        if self.win.clipboard_seq() != seq:
            QTimer.singleShot(15, self._on_copied)   # let the owner finish writing
        elif (time.monotonic() - t0) * 1000 > CLIPBOARD_WAIT_MS:
            self.saved_clip = None  # clipboard untouched; nothing to restore
            self._fail("Nothing was copied from the target input.")
        else:
            QTimer.singleShot(20, lambda: self._await_clipboard(seq, t0))

    def _on_copied(self) -> None:
        raw = QApplication.clipboard().text().strip()
        if not raw:
            return self._fail("The target input is empty.", restore=True)
        # Step 3: streamed inference on the thread pool.
        self.progress_target = 10.0
        self.waiting_first_token = True
        self.expected_tokens = self._expected_tokens()
        self._run(ollama_transform, self.model, self.mode, raw,
                  ok=self._on_transformed, fail=lambda m: self._fail(m, restore=True),
                  progress=self._on_tokens)

    # Progress bands: 0-10 prep/copy, 10-18 prompt eval, 18-98 generation, 100 pasted.
    def _on_tokens(self, n: int) -> None:
        if not self.busy:
            return
        self.waiting_first_token = False
        r = n / max(1, self.expected_tokens)
        # Linear up to 90% of the expected length, then approach (never hit) the cap.
        frac = r if r <= 0.9 else 0.9 + 0.1 * (1 - math.exp(-(r - 0.9) * 4))
        self.progress_target = max(self.progress_target, 18.0 + 80.0 * frac)

    def _expected_key(self) -> str:
        return f"expected_tokens/{self.model}/{self.mode}"

    def _expected_tokens(self) -> int:
        try:
            return max(10, int(float(self.settings.value(self._expected_key(), EXPECTED_TOKENS[self.mode]))))
        except (TypeError, ValueError):
            return EXPECTED_TOKENS[self.mode]

    def _learn_tokens(self, actual: int) -> None:
        ema = 0.7 * self._expected_tokens() + 0.3 * actual
        self.settings.setValue(self._expected_key(), round(ema))

    def _on_transformed(self, result: tuple[str, int]) -> None:
        text, tokens = result
        self._learn_tokens(tokens)
        self.waiting_first_token = False
        self.progress_target = 100.0
        # Step 4: paste back into the original window.
        if not self.win.focus(self.job_target):
            QApplication.clipboard().setText(text)
            self._finish()
            self.flash(COLOR_SUCCESS, 700)
            return self._show_tip("Target window is gone - result copied to clipboard.")
        QApplication.clipboard().setText(text)
        QTimer.singleShot(50, lambda: self.win.ctrl_chord(VK_A))
        QTimer.singleShot(90, lambda: (self.win.ctrl_chord(VK_V), self.flash(COLOR_SUCCESS, 900)))
        QTimer.singleShot(450, self._finish)   # let "100%" register before hiding

    def _fail(self, msg: str, restore: bool = False) -> None:
        if restore and self.saved_clip is not None:
            QApplication.clipboard().setMimeData(self.saved_clip)
        self._finish()
        self.flash(COLOR_ERROR, 1500)
        self._show_tip(msg)

    def _show_progress(self) -> None:
        self._update_pill()
        self.pill.show()
        self.pill.raise_()

    def _update_pill(self) -> None:
        if self.progress_target >= 100:
            label = "Pasting\u2026"
        elif self.progress_target < 10:
            label = "Copying text\u2026"
        elif self.waiting_first_token:
            label = "Thinking\u2026"
        else:
            label = "Rewriting\u2026"
        self.pill.set_progress(self.progress_shown, label)
        self.pill.place_beside(self)   # follows the overlay if it is dragged

    def _finish(self) -> None:
        self.busy = False
        self.pill.hide()
        self.saved_clip = None
        self._sync_anim()
        self.update()

    def _snapshot_clipboard(self):
        from PyQt6.QtCore import QMimeData
        src = QApplication.clipboard().mimeData()
        copy = QMimeData()
        if src is not None:
            for fmt in src.formats():
                try:
                    copy.setData(fmt, src.data(fmt))
                except Exception:  # noqa: BLE001 - exotic formats are best-effort
                    pass
        return copy

    # ------------------------------------------------------------- feedback
    def _show_tip(self, msg: str) -> None:
        QToolTip.showText(self.mapToGlobal(QPoint(0, -8)), msg, self, self.rect(), 4000)

    def flash(self, color: QColor, ms: int) -> None:
        self.flash_color = color
        self.flash_timer.start(ms)
        self.update()

    def _clear_flash(self) -> None:
        self.flash_color = None
        self.update()

    def _sync_anim(self) -> None:
        if self.busy or self.pressing:
            self.anim_timer.start()
        else:
            self.anim_timer.stop()

    def _on_anim_tick(self) -> None:
        if self.pressing and not self.dragging:
            self.hold_progress = min(1.0, (time.monotonic() - self.press_t) * 1000 / HOLD_MS)
        if self.busy:
            if self.waiting_first_token:   # prompt eval / model load: creep that never stalls
                self.progress_target += (18.0 - self.progress_target) * 0.006
            self.progress_shown += (self.progress_target - self.progress_shown) * 0.18
            self._update_pill()
        self._sync_anim()
        self.update()

    # ------------------------------------------------------------- painting
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        style = MODE_STYLES[self.mode]
        c = QPointF(WIDGET_SIZE / 2, WIDGET_SIZE / 2)
        r = DISC_RADIUS

        # Soft glow
        glow = QRadialGradient(c, r + 10)
        gc = QColor(self.flash_color if self.flash_color is not None else style.primary)
        gc.setAlpha(110 if (self.hover or self.flash_color is not None) else 60)
        glow.setColorAt(0.6, gc)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, r + 10, r + 10)

        # Disc
        p.setBrush(QColor(17, 24, 39, 235))
        p.drawEllipse(c, r, r)

        # Mode ring (conical gradient primary -> secondary)
        ring = QConicalGradient(c, 90)
        ring.setColorAt(0.0, style.primary)
        ring.setColorAt(0.5, style.secondary)
        ring.setColorAt(1.0, style.primary)
        pen = QPen(QBrush(self.flash_color if self.flash_color is not None else ring), 3.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, r - 1.5, r - 1.5)

        ring_rect = QRectF(c.x() - r - 5, c.y() - r - 5, 2 * (r + 5), 2 * (r + 5))

        # Hold progress stroke (clockwise from 12 o'clock) + color shift
        if self.hold_progress > 0:
            target = MODE_STYLES[MODE_LOOP if self.mode == MODE_STANDARD else MODE_STANDARD].primary
            hp = QPen(target, 3.5)
            hp.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(hp)
            p.drawArc(ring_rect, 90 * 16, int(-self.hold_progress * 360 * 16))

        inner = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        if self.busy:
            # Determinate progress: dark track (contrast on light backgrounds)
            # + green arc from 12 o'clock + green percentage
            p.setPen(QPen(COLOR_TRACK, 6.0))
            p.drawEllipse(ring_rect)
            sp = QPen(COLOR_PROGRESS, 4.5)
            sp.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(sp)
            p.drawArc(ring_rect, 90 * 16, int(-self.progress_shown / 100 * 360 * 16))
            p.setPen(COLOR_PROGRESS)
            p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            p.drawText(inner, Qt.AlignmentFlag.AlignCenter, f"{int(round(self.progress_shown))}%")
        else:
            # Center glyph: sparkle for standard, loop arrow for loop mode
            p.setPen(QColor("#f9fafb"))
            p.setFont(QFont("Segoe UI Symbol" if IS_WINDOWS else "Sans", 15, QFont.Weight.Bold))
            glyph = "✦" if self.mode == MODE_STANDARD else "↻"
            p.drawText(inner, Qt.AlignmentFlag.AlignCenter, glyph)

        # Mode badge (bottom-right)
        bc = QPointF(c.x() + r * math.cos(math.radians(45)), c.y() + r * math.sin(math.radians(45)))
        p.setPen(QPen(QColor(17, 24, 39), 2))
        p.setBrush(style.secondary if self.mode == MODE_LOOP else style.primary)
        p.drawEllipse(bc, 8, 8)
        p.setPen(QColor("#0b0f19"))
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.Black))
        p.drawText(QRectF(bc.x() - 8, bc.y() - 8, 16, 16), Qt.AlignmentFlag.AlignCenter, style.badge)

        # Offline indicator (top-right)
        if self.online is False:
            oc = QPointF(c.x() + r * 0.72, c.y() - r * 0.72)
            p.setPen(QPen(QColor(17, 24, 39), 2))
            p.setBrush(COLOR_ERROR)
            p.drawEllipse(oc, 5, 5)
        p.end()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def _headless_test(argv: list[str]) -> int:
    mode = MODE_LOOP if "--loop" in argv else MODE_STANDARD
    rest = [a for a in argv if a not in ("--test", "--loop")]
    raw = " ".join(rest) or "add dark mode to my settings page"
    t = time.perf_counter()
    try:
        text, tokens = ollama_transform(DEFAULT_MODEL, mode, raw)
    except OllamaError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(text)
    print(f"\n[{DEFAULT_MODEL} | {mode} | {tokens} tokens | {time.perf_counter() - t:.2f}s]", file=sys.stderr)
    return 0


INSTANCE_KEY = f"{APP_NAME}-overlay-instance"


def _take_over_single_instance(app: QApplication):
    """Ask any already-running overlay to quit, then own the instance channel,
    so relaunching `app.py` always replaces the old copy with the current code."""
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket

    probe = QLocalSocket()
    probe.connectToServer(INSTANCE_KEY)
    if probe.waitForConnected(300):
        probe.disconnectFromServer()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:       # wait for the old one to exit
            check = QLocalSocket()
            check.connectToServer(INSTANCE_KEY)
            if not check.waitForConnected(100):
                break
            check.disconnectFromServer()
            time.sleep(0.1)

    server = QLocalServer(app)
    QLocalServer.removeServer(INSTANCE_KEY)
    server.listen(INSTANCE_KEY)

    # Any connection is a takeover request; no payload to race against readyRead.
    server.newConnection.connect(app.quit)
    return server


def main() -> int:
    if "--test" in sys.argv:
        return _headless_test(sys.argv[1:])
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    _server = _take_over_single_instance(app)  # noqa: F841 - keep alive
    w = OverlayWidget()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
