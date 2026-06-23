"""
全屏截图 + 框选 — 每个显示器单独一个 Widget，互不影响
"""

import numpy as np
from PIL import Image

from PyQt6.QtWidgets import (
    QWidget, QPushButton, QApplication,
)
from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPoint, pyqtSignal, QTimer,
)
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QImage,
    QPainterPath, QCursor,
)

from config import (
    BUTTON_WIDTH, BUTTON_HEIGHT,
    BUTTON_GAP, BUTTON_MARGIN, BUTTON_STYLE,
    SELECTION_BORDER_COLOR, SELECTION_BORDER_WIDTH,
    SELECTION_OVERLAY_ALPHA, MIN_SELECTION_SIZE,
)


class ScreenCaptureWidget(QWidget):
    """单个显示器上的全屏覆盖层"""

    # 信号: (选框QRect逻辑像素, 选框QRect物理像素, 本显示器numpy物理像素数组, 操作类型)
    action_triggered = pyqtSignal(QRect, QRect, np.ndarray, str)
    cancelled = pyqtSignal()

    def __init__(self, screenshot_np: np.ndarray, mon_info: dict):
        """
        screenshot_np: mss 截取的该显示器物理像素 (BGRA)
        mon_info: mss 该显示器的字典 (left, top, width, height)
        """
        super().__init__()
        self._screenshot_np = screenshot_np
        self._mon_info = mon_info

        # 找到该显示器对应的 Qt QScreen
        self._qt_screen = self._find_qt_screen(mon_info)
        if self._qt_screen is None:
            raise RuntimeError(f"未找到与 mss monitor {mon_info.get('left',0)},{mon_info.get('top',0)} 匹配的 Qt 屏幕")

        screen_geo = self._qt_screen.geometry()  # 逻辑像素

        # 计算缩放：物理像素 → 逻辑像素
        self._scale_x = mon_info['width'] / screen_geo.width()
        self._scale_y = mon_info['height'] / screen_geo.height()

        # 生成用于显示的 QImage — 保持物理分辨率，绘制时用 QPainter 自动缩放
        qimg_full = self._np_to_qimage(screenshot_np)

        # 使用 devicePixelRatio 让 Qt 自动处理高DPI渲染 (整数倍)
        scale = max(self._scale_x, self._scale_y)
        dpr = max(1, round(scale))
        qimg_full.setDevicePixelRatio(dpr)
        self._screenshot_qimage = qimg_full
        # 原始物理分辨率的备份用于裁图
        self._img_physical_w = mon_info['width']
        self._img_physical_h = mon_info['height']

        # 框选状态
        self._start_point: QPoint | None = None
        self._end_point: QPoint | None = None
        self._selecting = False
        self._selection_done = False

        # 按钮
        self._btn_ocr: QPushButton | None = None
        self._btn_translate: QPushButton | None = None

        self._setup_ui()

    # ==================================================================
    # 查找对应的 Qt 屏幕
    # ==================================================================
    @staticmethod
    def _find_qt_screen(mon_info: dict):
        """通过 mss 的 left/top 与 Qt 屏幕的 physicalGeometry 匹配"""
        mss_left, mss_top = mon_info['left'], mon_info['top']
        best, best_dist = None, 999999
        for screen in QApplication.screens():
            sg = screen.geometry()
            dist = abs(sg.x() - mss_left) + abs(sg.y() - mss_top)
            if dist < best_dist:
                best_dist = dist
                best = screen
        return best  # 返回最近匹配的屏幕

    # ==================================================================
    # UI 初始化
    # ==================================================================
    def _setup_ui(self):
        sg = self._qt_screen.geometry()
        self.setGeometry(sg)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setMouseTracking(True)
        self._create_buttons()

    def _create_buttons(self):
        self._btn_ocr = QPushButton("📋 提取文字", self)
        self._btn_ocr.setFixedSize(BUTTON_WIDTH, BUTTON_HEIGHT)
        self._btn_ocr.setStyleSheet(BUTTON_STYLE)
        self._btn_ocr.clicked.connect(self._on_ocr)
        self._btn_ocr.hide()

        self._btn_translate = QPushButton("🌐 翻译", self)
        self._btn_translate.setFixedSize(BUTTON_WIDTH, BUTTON_HEIGHT)
        self._btn_translate.setStyleSheet(BUTTON_STYLE)
        self._btn_translate.clicked.connect(self._on_translate)
        self._btn_translate.hide()

    # ==================================================================
    # 绘制
    # ==================================================================
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. 绘制该显示器的截图（已缩放到逻辑像素尺寸）
        painter.drawImage(self.rect(), self._screenshot_qimage)

        # 2. 选框外部半透明遮罩
        sel_rect = self._get_selection_rect()
        has_valid_sel = sel_rect and sel_rect.width() > 5 and sel_rect.height() > 5

        if has_valid_sel:
            clip_path = QPainterPath()
            clip_path.addRect(QRectF(self.rect()))
            sel_path = QPainterPath()
            sel_path.addRect(QRectF(sel_rect))
            clip_path = clip_path.subtracted(sel_path)
            painter.setClipPath(clip_path)

        painter.fillRect(self.rect(), QColor(0, 0, 0, SELECTION_OVERLAY_ALPHA))
        painter.setClipping(False)

        # 3. 蓝色边框
        if has_valid_sel:
            pen = QPen(QColor(SELECTION_BORDER_COLOR), SELECTION_BORDER_WIDTH)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(sel_rect)

    # ==================================================================
    # 鼠标事件
    # ==================================================================
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._selection_done:
                self._on_cancel()
                return
            self._start_point = event.pos()
            self._end_point = event.pos()
            self._selecting = True
            self._selection_done = False
            self._hide_buttons()

    def mouseMoveEvent(self, event):
        if self._selecting:
            self._end_point = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._end_point = event.pos()
            self._selecting = False

            sel_rect = self._get_selection_rect()
            if sel_rect and sel_rect.width() >= MIN_SELECTION_SIZE and sel_rect.height() >= MIN_SELECTION_SIZE:
                self._selection_done = True
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                self._position_buttons(sel_rect)
                self.update()
            else:
                self._start_point = None
                self._end_point = None
                self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancel()
        else:
            super().keyPressEvent(event)

    # ==================================================================
    # 按钮布局
    # ==================================================================
    def _position_buttons(self, sel_rect: QRect):
        win_rect = self.geometry()
        anchor_x = sel_rect.right() + BUTTON_MARGIN
        anchor_y = sel_rect.bottom() - BUTTON_HEIGHT * 2 - BUTTON_GAP

        if anchor_x + BUTTON_WIDTH > win_rect.right():
            anchor_x = sel_rect.left() - BUTTON_WIDTH - BUTTON_MARGIN
        if anchor_y + BUTTON_HEIGHT * 2 + BUTTON_GAP > win_rect.bottom():
            anchor_y = win_rect.bottom() - BUTTON_HEIGHT * 2 - BUTTON_GAP - BUTTON_MARGIN
        if anchor_y < win_rect.top():
            anchor_y = sel_rect.top() + BUTTON_MARGIN
        if anchor_x < win_rect.left():
            anchor_x = win_rect.left() + BUTTON_MARGIN

        self._btn_ocr.move(anchor_x, anchor_y)
        self._btn_translate.move(anchor_x, anchor_y + BUTTON_HEIGHT + BUTTON_GAP)
        self._btn_ocr.show()
        self._btn_translate.show()

    def _hide_buttons(self):
        if self._btn_ocr:
            self._btn_ocr.hide()
        if self._btn_translate:
            self._btn_translate.hide()

    # ==================================================================
    # 信号发送 — 将选框从逻辑坐标转换为本显示器的物理像素坐标
    # ==================================================================
    def _on_ocr(self):
        sel_rect = self._get_selection_rect()
        if sel_rect:
            physical_rect = self._to_physical(sel_rect)
            self.hide()
            QTimer.singleShot(50, lambda: self.action_triggered.emit(
                sel_rect, physical_rect, self._screenshot_np, "extract"
            ))

    def _on_translate(self):
        sel_rect = self._get_selection_rect()
        if sel_rect:
            physical_rect = self._to_physical(sel_rect)
            self.hide()
            QTimer.singleShot(50, lambda: self.action_triggered.emit(
                sel_rect, physical_rect, self._screenshot_np, "translate"
            ))

    def _on_cancel(self):
        self.hide()
        self.cancelled.emit()

    # ==================================================================
    # 工具方法
    # ==================================================================
    def _get_selection_rect(self) -> QRect | None:
        if self._start_point is None or self._end_point is None:
            return None
        return QRect(self._start_point, self._end_point).normalized()

    def _to_physical(self, logical_rect: QRect) -> QRect:
        """逻辑像素选框 → 物理像素选框（用于裁图）"""
        return QRect(
            int(logical_rect.x() * self._scale_x),
            int(logical_rect.y() * self._scale_y),
            int(logical_rect.width() * self._scale_x),
            int(logical_rect.height() * self._scale_y),
        )

    @staticmethod
    def _np_to_qimage(arr: np.ndarray) -> QImage:
        h, w, c = arr.shape
        if c == 4:
            arr_rgb = arr[..., [2, 1, 0, 3]].copy()
            fmt = QImage.Format.Format_RGBA8888
        elif c == 3:
            arr_rgb = arr[..., [2, 1, 0]].copy()
            fmt = QImage.Format.Format_RGB888
        else:
            raise ValueError(f"不支持的通道数: {c}")
        qimg = QImage(arr_rgb.tobytes(), w, h, arr_rgb.strides[0], fmt)
        return qimg.copy()

    @staticmethod
    def crop_region(screenshot_np: np.ndarray, rect: QRect) -> Image.Image:
        """从本显示器的 numpy 物理像素数组中裁切指定区域"""
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        sh, sw = screenshot_np.shape[:2]
        x = max(0, min(x, sw - 1))
        y = max(0, min(y, sh - 1))
        w = max(1, min(w, sw - x))
        h = max(1, min(h, sh - y))

        roi = screenshot_np[y:y + h, x:x + w]
        if roi.shape[2] == 4:
            roi = roi[..., [2, 1, 0, 3]]
        elif roi.shape[2] == 3:
            roi = roi[..., [2, 1, 0]]
        return Image.fromarray(roi)
