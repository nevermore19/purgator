import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QFrame, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from purgator.tasks import Cancelled
from purgator.ui.colors import BACKGROUND, BORDER, TEXT
from purgator.ui.components import RatioBar, RingChart, page_layout
from purgator.workers import Worker

BOX_STYLE = (
    f"QGroupBox {{ background-color: {BACKGROUND}; border: 1px solid {BORDER}; border-radius: 15px; }}"
)
TITLE_STYLE = f"font-size: 20px; font-weight: 600; color: {TEXT};"


class _HomeSizeScan:
    """Measures /home with du off the GUI thread; it can take seconds."""

    id = "home_size"

    def __init__(self, path: str) -> None:
        self.path = path
        self.dry_run = True

    def run(self, report, is_cancelled):
        proc = subprocess.Popen(
            ["du", "-s", "--block-size=1", self.path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        while proc.poll() is None:
            if is_cancelled():
                proc.kill()
                proc.wait()
                raise Cancelled
            try:
                proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
        out = proc.stdout.read()
        # du exits 1 on unreadable dirs but still prints the total
        try:
            return int(out.split()[0])
        except (IndexError, ValueError):
            return shutil.disk_usage(self.path).used


class OverviewPage(QWidget):
    """The disk usage, the share of the home directory and the scheduled tasks."""

    def __init__(self, pool: QThreadPool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root_candidates = ["/run/host/root", "/home", "/"]
        root_path = "/"
        for c in root_candidates:
            try:
                p = Path(c)
                if p.exists():
                    root_path = c
                    break
            except Exception:
                continue
        usage = shutil.disk_usage(root_path)
        self._disk_used = usage.used
        home_path_on_root = "/home"
        if root_path == "/run/host/root":
            home_path_on_root = "/run/host/root/home"
        layout = page_layout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        box_width = 340
        box = QGroupBox()
        box.setFixedWidth(box_width)
        box.setStyleSheet(BOX_STYLE)
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(10, 10, 10, 4)
        box_layout.setSpacing(0)
        box_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        title = QLabel("Disk usage")
        title.setStyleSheet(TITLE_STYLE)
        box_layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignLeft)
        box_layout.addSpacing(0)
        chart_w = box_width - 20
        chart_h = int(chart_w * 0.86) + 6
        view = self._build_disk_usage_chart(usage, chart_w, chart_h)
        box_layout.addWidget(view)
        available = QLabel(f"{usage.free / (1024**3):.0f} GiB available")
        available.setAlignment(Qt.AlignmentFlag.AlignCenter)
        available.setStyleSheet(f"font-size: 16px; color: {TEXT}; background: transparent;")
        box_layout.addSpacing(2)
        box_layout.addWidget(available)
        box_layout.addSpacing(24)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setStyleSheet(f"color: {BORDER}; background-color: {BORDER};")
        separator.setFixedHeight(1)
        box_layout.addWidget(separator)
        box_layout.addSpacing(8)
        bar_view = self._build_home_to_disk_bar()
        box_layout.addWidget(bar_view)
        box_layout.addSpacing(60)

        right_container = QGroupBox()
        right_container.setFixedWidth(box_width)
        right_container.setStyleSheet(BOX_STYLE)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(10, 10, 10, 4)
        right_layout.setSpacing(8)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        right_title = QLabel("Scheduled tasks")
        right_title.setStyleSheet(TITLE_STYLE)
        right_layout.addWidget(right_title, alignment=Qt.AlignmentFlag.AlignLeft)
        right_container.setFixedHeight(box.sizeHint().height() // 2)

        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        row.setSpacing(60)
        row.addWidget(box, alignment=Qt.AlignmentFlag.AlignTop)
        row.addWidget(right_container, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(row)
        layout.addStretch()

        worker = Worker(_HomeSizeScan(home_path_on_root))
        self._home_size_worker = worker  # the pool does not delete it
        worker.signals.finished.connect(self._on_home_size)
        pool.start(worker)

    def _build_disk_usage_chart(self, usage, width: int = 360, height: int = 380) -> QWidget:
        used_gb = usage.used / (1024**3)
        total_gb = usage.total / (1024**3)
        used_pct = usage.used / usage.total * 100 if usage.total else 0
        used_frac = usage.used / usage.total if usage.total else 0

        view = RingChart(used_frac)
        view.setFixedSize(width, height)

        center = QLabel(
            "<table cellpadding='0' cellspacing='0' align='center'>"
            f"<tr><td align='center' style='line-height: 70%;'><span style='font-size: 40px;'>{used_pct:.0f}%</span></td></tr>"
            "<tr><td align='center' style='padding-top: 5px; padding-bottom: 10px;'>"
            f"<span style='font-size: 13px; color: {TEXT};'>used</span></td></tr>"
            f"<tr><td align='center'><span style='font-size: 16px;'>{used_gb:.0f} GiB / {total_gb:.0f} GiB</span></td></tr>"
            "</table>",
            view,
        )
        center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center.setStyleSheet(f"color: {TEXT}; background: transparent;")
        center.setGeometry(0, 0, width, height)
        center.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return view

    def _build_home_to_disk_bar(self) -> QWidget:
        bar_width = 300
        bar = RatioBar(0.0)
        self._home_bar = bar
        bar.setFixedHeight(12)
        bar.setFixedWidth(bar_width)

        section_title = QLabel("Home directory")
        section_title.setStyleSheet(f"{TITLE_STYLE} background: transparent;")
        section_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        lbl = QLabel(f"<span style='font-size:16px;color:{TEXT};'>… GiB</span>")
        self._home_size_label = lbl
        lbl.setStyleSheet("background: transparent;")
        lbl.setFixedWidth(bar_width)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 12)
        vbox.setSpacing(0)
        vbox.addWidget(section_title)
        vbox.addSpacing(16)
        vbox.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignHCenter)
        vbox.addSpacing(4)
        vbox.addWidget(bar, alignment=Qt.AlignmentFlag.AlignHCenter)
        vbox.addSpacing(16)
        pct = QLabel(f"<span style='font-size:16px;color:{TEXT};'>Measuring your files…</span>")
        self._home_pct_label = pct
        pct.setStyleSheet("background: transparent;")
        pct.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        vbox.addWidget(pct, alignment=Qt.AlignmentFlag.AlignHCenter)

        return container

    def _on_home_size(self, _task_id: str, home_used: int) -> None:
        home_frac = home_used / max(self._disk_used, 1)
        self._home_bar.set_frac(home_frac)
        self._home_size_label.setText(
            f"<span style='font-size:16px;color:{TEXT};'>{home_used/(1024**3):.0f} GiB</span>"
        )
        self._home_pct_label.setText(
            f"<span style='font-size:16px;color:{TEXT};'>{home_frac * 100:.0f}% of disk space is used by your files</span>"
        )

    def shutdown(self) -> None:
        """Stop measuring the home directory when the window closes."""
        self._home_size_worker.cancel()
