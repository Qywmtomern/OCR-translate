"""
文字贴图 — 段落级精确定位。
- 像素投影 → 行密度权重 → 按权重比例分配选区空间
- OCR 文本按空行分段；每段一个 QLabel，段内统一字号
- 段间间距紧凑不浪费空间
- 拖动条含关闭/复制按钮
"""

import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QPushButton, QApplication, QLabel, QHBoxLayout,
)
from PyQt6.QtCore import (
    Qt, QRect, QPoint, QPropertyAnimation,
    QEasingCurve, pyqtSignal,
)
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QPen, QMouseEvent,
)

from config import FONT_FAMILY


DRAG_BAR_H = 24
BTN_SIZE = 20


# ═══════════════════════════════════════════════════════════════════
# 像素投影 — 仅用于获取行"密度权重"（高行=大字号），不用于坐标
# ═══════════════════════════════════════════════════════════════════

def _row_weights(pil_image) -> list[float]:
    """返回每行'暗像素密度'列表。空列表 = 检测失败。"""
    gray = pil_image.convert('L')
    arr = np.array(gray, dtype=np.float32)
    img_h = arr.shape[0]
    if img_h < 5:
        return []

    inv = 255.0 - arr
    proj = np.mean(inv, axis=1)
    p90 = float(np.percentile(proj, 90))
    p50 = float(np.percentile(proj, 50))
    if p90 - p50 < 4.0:
        return []

    threshold = p50 + (p90 - p50) * 0.22
    mask = proj > threshold

    # 提取连续文字段 → 每行一个 (start, end, peak_intensity)
    segments = []
    in_run, start = False, 0
    for y in range(img_h):
        if mask[y] and not in_run:
            in_run, start = True, y
        elif not mask[y] and in_run:
            in_run = False
            if y - start >= 3:
                peak = float(np.max(proj[start:y]))
                segments.append((start, y, peak))
    if in_run:
        y = img_h
        if y - start >= 3:
            peak = float(np.max(proj[start:y]))
            segments.append((start, y, peak))

    if not segments:
        return []

    # 过滤碎片
    avg_h = sum(e - s for s, e, _ in segments) / len(segments)
    segments = [(s, e, p) for s, e, p in segments if e - s >= max(3, avg_h * 0.35)]
    if not segments:
        return []

    # 合并紧密段
    merged = []
    for s, e, p in segments:
        if (
            merged
            and s - merged[-1][1] < max(avg_h * 0.45, 2)
        ):
            ps, pe, pp = merged.pop()
            merged.append((ps, e, (pp + p) / 2))
        else:
            merged.append((s, e, p))
    return [p for _, _, p in merged]


# ═══════════════════════════════════════════════════════════════════
# TextOverlay
# ═══════════════════════════════════════════════════════════════════

class TextOverlay(QWidget):
    """段落级画布贴图"""

    dismissed = pyqtSignal()

    def __init__(
        self,
        text: str,
        target_rect: QRect,
        region_image=None,
    ):
        super().__init__()
        self._raw_text = text
        self._target_rect = target_rect
        self._region_image = region_image

        self._dragging = False
        self._drag_offset = QPoint()
        self._para_labels: list[QLabel] = []

        self._setup_ui()
        self._layout_paragraphs()

    # ==================================================================
    # UI
    # ==================================================================
    def _setup_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setGeometry(self._target_rect)
        self.setMinimumSize(80, 60)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # ── 拖动条 ──
        self._drag_bar = QWidget(self)
        self._drag_bar.setObjectName("dragBar")
        self._drag_bar.setStyleSheet("""
            QWidget#dragBar {
                background: qlineargradient(x1:0 y1:0, x2:0 y2:1,
                    stop:0 rgba(66,133,244,200), stop:1 rgba(66,133,244,120));
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
            }
        """)
        self._drag_bar.setCursor(Qt.CursorShape.SizeAllCursor)

        bar_layout = QHBoxLayout(self._drag_bar)
        bar_layout.setContentsMargins(4, 2, 4, 2)
        bar_layout.setSpacing(4)

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
        self._close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._close_btn.setStyleSheet("""
            QPushButton { background: rgba(220,50,50,210); color: white;
                border: none; border-radius: 10px;
                font-size: 12px; font-weight: bold; padding: 0; }
            QPushButton:hover { background: rgba(240,60,60,240); }
        """)
        self._close_btn.setToolTip("关闭 (Esc / 双击)")
        self._close_btn.clicked.connect(self._on_dismiss)

        self._copy_btn = QPushButton("▣")
        self._copy_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
        self._copy_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._copy_btn.setStyleSheet("""
            QPushButton { background: rgba(66,133,244,210); color: white;
                border: none; border-radius: 10px;
                font-size: 11px; font-weight: bold; padding: 0; }
            QPushButton:hover { background: rgba(80,150,255,240); }
        """)
        self._copy_btn.setToolTip("复制全部文字 (Ctrl+C)")
        self._copy_btn.clicked.connect(self._on_copy)

        self._drag_label = QLabel("拖动")
        self._drag_label.setStyleSheet(
            "color: white; font-size: 10px; background: transparent;"
        )
        self._drag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        bar_layout.addWidget(self._close_btn)
        bar_layout.addWidget(self._copy_btn)
        bar_layout.addStretch()
        bar_layout.addWidget(self._drag_label)
        bar_layout.addStretch()

        # 拖动条事件 = 空白区拖动
        self._drag_bar.installEventFilter(self)

    # ==================================================================
    # eventFilter
    # ==================================================================
    def eventFilter(self, obj, event):
        if obj is self._drag_bar:
            et = event.type()
            if et == event.Type.MouseButtonPress:
                if isinstance(
                    self._drag_bar.childAt(event.position().toPoint()),
                    QPushButton,
                ):
                    return False
                self._dragging = True
                self._drag_offset = (
                    event.globalPosition().toPoint()
                    - self.frameGeometry().topLeft()
                )
                return True
            if et == event.Type.MouseMove and self._dragging:
                self.move(
                    event.globalPosition().toPoint() - self._drag_offset
                )
                return True
            if et == event.Type.MouseButtonRelease and self._dragging:
                self._dragging = False
                return True
        return super().eventFilter(obj, event)

    # ==================================================================
    # 核心：按 OCR 段落结构 + 像素权重分配空间
    # ==================================================================
    def _layout_paragraphs(self):
        for lbl in self._para_labels:
            lbl.deleteLater()
        self._para_labels = []

        # ── 1. 按空行分段 ──
        paragraphs: list[str] = []
        for chunk in self._raw_text.split('\n\n'):
            c = chunk.strip()
            if c:
                paragraphs.append(c)
        if not paragraphs:
            return

        para_line_counts = [p.count('\n') + 1 for p in paragraphs]
        total_lines = sum(para_line_counts)
        n_para = len(paragraphs)

        w = self.width()
        h = self.height()
        content_top = DRAG_BAR_H + 4
        content_h = max(10, h - DRAG_BAR_H - 8)

        # ── 2. 像素权重 → 相对行高比例 ──
        if self._region_image is not None:
            weights = _row_weights(self._region_image)
        else:
            weights = []

        # 构建所有 OCR 行的扁平列表（按段落顺序）
        all_lines_flat: list[str] = []
        for p in paragraphs:
            all_lines_flat.extend(p.split('\n'))

        if weights and abs(len(weights) - total_lines) <= total_lines // 2 + 1:
            wgt_per_line = []
            for i in range(total_lines):
                pw = weights[i] if i < len(weights) else (weights[-1] if weights else 1.0)
                wgt_per_line.append(max(0.5, pw ** 0.6))
        else:
            # 所有行等权重（最稳定）
            wgt_per_line = [1.0] * total_lines

        # ── 3. 段间距 ──
        para_gap = min(6, max(2, content_h // 40))

        # 扣除段间距后的可用高度
        avail = content_h - (n_para - 1) * para_gap

        # 按权重分配可用高度
        total_weight = sum(wgt_per_line)
        if total_weight == 0:
            total_weight = total_lines

        # 每行至少 14px
        MIN_LINE_H = 14
        line_heights = [
            max(MIN_LINE_H, int(avail * wgt_per_line[i] / total_weight))
            for i in range(total_lines)
        ]

        # 归一化：确保总和 ≤ avail
        sum_h = sum(line_heights)
        if sum_h > avail:
            scale = avail / sum_h
            line_heights = [max(MIN_LINE_H, int(h * scale)) for h in line_heights]
            # 二次归一
            sum_h = sum(line_heights)
            if sum_h > avail:
                # 从最大的行开始减
                sorted_idx = sorted(range(total_lines), key=lambda i: line_heights[i], reverse=True)
                for idx in sorted_idx:
                    if sum_h <= avail:
                        break
                    line_heights[idx] -= 1
                    sum_h -= 1

        # ── 4. 聚合为段落高度，创建 QLabel ──
        cursor_y = content_top
        margin_y = max(2, (avail - sum_h) // 2) if sum_h < avail else 0
        cursor_y += margin_y

        idx = 0
        for pi, para_text in enumerate(paragraphs):
            pc = para_line_counts[pi]
            ph = sum(line_heights[idx:idx + pc])

            # 字号 = 行高 × 0.50，上限 16px（防止选区过大时字体偏大）
            avg_lh = ph // pc
            font_px = max(12, min(int(avg_lh * 0.50), 16))

            label = QLabel(self)
            label.setText(para_text)
            label.setWordWrap(True)
            label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            label.setCursor(Qt.CursorShape.IBeamCursor)
            label.setStyleSheet(
                "color:#000; background:transparent; padding:1px 4px;"
            )
            f = QFont(FONT_FAMILY)
            f.setPixelSize(font_px)
            label.setFont(f)
            label.setGeometry(4, cursor_y, w - 8, ph)
            label.show()
            self._para_labels.append(label)

            cursor_y += ph + para_gap
            idx += pc

    # ==================================================================
    # 布局
    # ==================================================================
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._drag_bar.setGeometry(0, 0, self.width(), DRAG_BAR_H)

    # ==================================================================
    # 外观
    # ==================================================================
    def showEvent(self, event):
        super().showEvent(event)
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(120)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.setPen(QPen(QColor(160, 160, 160), 1))
        painter.drawRoundedRect(self.rect(), 6, 6)

    # ==================================================================
    # 键盘 / 动作
    # ==================================================================
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._on_dismiss()
        elif (
            event.modifiers() == Qt.KeyboardModifier.ControlModifier
            and event.key() == Qt.Key.Key_C
        ):
            self._on_copy()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._on_dismiss()

    def _on_copy(self):
        QApplication.clipboard().setText(self._raw_text)

    def _on_dismiss(self):
        self.hide()
        self.dismissed.emit()
        self.deleteLater()
