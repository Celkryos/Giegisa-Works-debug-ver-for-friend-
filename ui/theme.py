"""Giegisa 的统一冰蓝玻璃界面主题。

外部只需要调用 install_ice_glass_theme(app, background_path)。
背景缩放、按钮角色迁移和控件样式都集中在这里，业务窗口不需要知道
图片如何裁切，也不需要分别复制样式。
"""

import os

from PyQt6.QtCore import QEvent, QObject, QPoint, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSizeGrip,
    QWidget,
)


ICE_GLASS_QSS = r"""
QDialog {
    color: #24415f;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 13px;
}
QDialog QLabel {
    color: #24415f;
    background: transparent;
}
QDialog QWidget#iceTitleBar {
    background: transparent;
}
QDialog QLabel#iceTitleText {
    color: #245373;
    font-weight: 600;
    padding-left: 4px;
}
QDialog QPushButton#iceCloseButton {
    min-width: 27px;
    max-width: 27px;
    min-height: 27px;
    max-height: 27px;
    color: #7b4660;
    background-color: rgba(255, 245, 248, 185);
    border: 1px solid rgba(218, 132, 155, 150);
    border-radius: 8px;
    padding: 0;
    font-size: 17px;
    font-weight: 400;
}
QDialog QPushButton#iceCloseButton:hover {
    color: white;
    background-color: rgba(215, 76, 108, 225);
    border-color: rgba(255, 225, 233, 235);
}
QDialog QGroupBox {
    color: #24415f;
    background-color: rgba(247, 252, 255, 196);
    border: 1px solid rgba(116, 188, 241, 150);
    border-radius: 16px;
    margin-top: 13px;
    padding: 13px 10px 10px 10px;
    font-weight: 600;
}
QDialog QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 7px;
    color: #2775aa;
    background-color: rgba(238, 249, 255, 225);
    border-radius: 5px;
}
QDialog QLineEdit,
QDialog QTextEdit,
QDialog QComboBox,
QDialog QSpinBox,
QDialog QDateEdit,
QDialog QTimeEdit {
    color: #24415f;
    background-color: rgba(255, 255, 255, 202);
    border: 1px solid rgba(118, 184, 233, 155);
    border-radius: 10px;
    padding: 6px 8px;
    selection-background-color: rgba(67, 157, 226, 205);
    selection-color: white;
}
QDialog QListWidget,
QDialog QScrollArea {
    color: #24415f;
    background-color: rgba(250, 254, 255, 174);
    border: 1px solid rgba(118, 184, 233, 155);
    border-radius: 12px;
    padding: 6px 8px;
    selection-background-color: rgba(67, 157, 226, 205);
    selection-color: white;
}
QDialog QLineEdit:focus,
QDialog QTextEdit:focus,
QDialog QListWidget:focus,
QDialog QComboBox:focus,
QDialog QSpinBox:focus,
QDialog QDateEdit:focus,
QDialog QTimeEdit:focus {
    border: 2px solid rgba(42, 154, 235, 220);
    background-color: rgba(255, 255, 255, 226);
}
QDialog QListWidget {
    outline: 0;
}
QDialog QListWidget::item {
    color: #24415f;
    background-color: transparent;
    border-radius: 8px;
    padding: 6px;
    margin: 2px;
}
QDialog QListWidget::item:hover {
    background-color: rgba(197, 231, 255, 165);
}
QDialog QListWidget::item:selected {
    color: #174769;
    background-color: rgba(142, 207, 249, 190);
}
QDialog QScrollArea,
QDialog QScrollArea > QWidget > QWidget {
    background-color: transparent;
}
QDialog QPushButton {
    min-height: 25px;
    color: #245373;
    background-color: rgba(244, 251, 255, 205);
    border: 1px solid rgba(91, 172, 231, 175);
    border-radius: 10px;
    padding: 6px 12px;
}
QDialog QPushButton[calendarCell="true"] {
    min-width: 0;
    min-height: 24px;
    max-height: 24px;
    padding: 0;
    border-radius: 5px;
}
QDialog QPushButton:hover {
    color: #123f60;
    background-color: rgba(215, 241, 255, 232);
    border: 1px solid rgba(44, 150, 228, 225);
}
QDialog QPushButton:pressed {
    color: #173d58;
    background-color: rgba(173, 220, 249, 225);
    border: 1px solid rgba(35, 129, 199, 230);
    padding-top: 8px;
    padding-bottom: 4px;
}
QDialog QPushButton:checked,
QDialog QPushButton[uiRole="primary"] {
    color: white;
    background-color: rgba(45, 155, 234, 224);
    border: 1px solid rgba(255, 255, 255, 215);
    font-weight: 600;
}
QDialog QPushButton:checked:hover,
QDialog QPushButton[uiRole="primary"]:hover {
    background-color: rgba(29, 137, 218, 236);
    border: 1px solid rgba(225, 246, 255, 245);
}
QDialog QPushButton[uiRole="danger"] {
    color: #9f3850;
    background-color: rgba(255, 235, 240, 220);
    border: 1px solid rgba(229, 124, 148, 178);
}
QDialog QPushButton[uiRole="danger"]:hover {
    color: white;
    background-color: rgba(218, 83, 113, 225);
    border: 1px solid rgba(255, 222, 230, 238);
}
QDialog QPushButton[uiRole="quiet"] {
    min-height: 18px;
    color: #5f7d93;
    background-color: transparent;
    border: 1px solid transparent;
    text-align: left;
    padding: 4px 6px;
}
QDialog QPushButton[uiRole="quiet"]:hover {
    color: #226b9d;
    background-color: rgba(224, 244, 255, 150);
    border: 1px solid rgba(120, 190, 239, 125);
}
QDialog QPushButton:disabled {
    color: rgba(70, 103, 126, 115);
    background-color: rgba(239, 246, 250, 120);
    border-color: rgba(135, 174, 200, 90);
}
QDialog QCheckBox {
    color: #24415f;
    spacing: 7px;
    background: transparent;
}
QDialog QCheckBox::indicator {
    width: 16px;
    height: 16px;
    background-color: rgba(255, 255, 255, 218);
    border: 1px solid rgba(79, 159, 218, 205);
    border-radius: 4px;
}
QDialog QCheckBox::indicator:hover {
    border: 2px solid rgba(37, 148, 228, 230);
}
QDialog QCheckBox::indicator:checked {
    background-color: rgba(48, 157, 234, 230);
    border: 3px solid rgba(219, 244, 255, 245);
}
QDialog QComboBox::drop-down,
QDialog QDateEdit::drop-down,
QDialog QTimeEdit::drop-down {
    width: 24px;
    border: 0;
    background-color: rgba(192, 229, 252, 135);
    border-top-right-radius: 9px;
    border-bottom-right-radius: 9px;
}
QDialog QComboBox::down-arrow,
QDialog QDateEdit::down-arrow,
QDialog QTimeEdit::down-arrow {
    image: url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAoAAAAGCAYAAAD68A/GAAAAKElEQVR4nGNQcYz/z0AAgNWQpBCfYrg8jIFNMYocMgdZMYY4ugAuDAB2SjhhqIWulAAAAABJRU5ErkJggg==);
    width: 10px;
    height: 6px;
}
QDialog QSpinBox::up-button,
QDialog QSpinBox::down-button {
    width: 20px;
    border: 0;
    background-color: rgba(192, 229, 252, 135);
}
QDialog QSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: 9px;
}
QDialog QSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 9px;
}
QDialog QSpinBox::up-arrow {
    image: url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAoAAAAGCAYAAAD68A/GAAAAJUlEQVR4nGNgIBaoOMb/R8Y4xbEpwqaYAZcidMUM+BQhKyZaIQDs6ybDffugvQAAAABJRU5ErkJggg==);
    width: 10px;
    height: 6px;
}
QDialog QSpinBox::down-arrow {
    image: url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAoAAAAGCAYAAAD68A/GAAAAKElEQVR4nGNQcYz/z0AAgNWQpBCfYrg8jIFNMYocMgdZMYY4ugAuDAB2SjhhqIWulAAAAABJRU5ErkJggg==);
    width: 10px;
    height: 6px;
}
QToolTip {
    color: #20435d;
    background-color: rgba(245, 252, 255, 245);
    border: 1px solid rgba(83, 164, 222, 210);
    border-radius: 7px;
    padding: 5px;
}
QMenu {
    color: #24415f;
    background-color: rgba(248, 253, 255, 248);
    border: 1px solid rgba(100, 175, 229, 190);
    border-radius: 9px;
    padding: 5px;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 13px;
}
QMenu::item {
    padding: 7px 24px 7px 13px;
    background-color: transparent;
    border-radius: 6px;
}
QMenu::item:selected {
    color: #174769;
    background-color: rgba(190, 229, 253, 215);
}
QMenu::separator {
    height: 1px;
    background-color: rgba(100, 175, 229, 115);
    margin: 5px 8px;
}
"""


class IceBackgroundWidget(QWidget):
    """在透明的无边框窗口底部绘制圆角背景。"""

    def __init__(self, parent, pixmap):
        super().__init__(parent)
        self.source = pixmap
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setObjectName("iceBackground")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)
        painter.setClipPath(path)

        if not self.source.isNull() and self.width() > 0 and self.height() > 0:
            scaled = self.source.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            left = max(0, (scaled.width() - self.width()) // 2)
            top = max(0, (scaled.height() - self.height()) // 2)
            painter.drawPixmap(0, 0, scaled, left, top, self.width(), self.height())
        else:
            painter.fillPath(path, QColor(237, 248, 255, 245))

        overlay_opacity = int(self.property("darkOverlayOpacity") or 0)
        if overlay_opacity > 0:
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Multiply)
            painter.fillPath(
                path, QColor(43, 50, 58, max(0, min(255, overlay_opacity))))
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver)

        painter.setClipping(False)
        painter.setPen(QPen(QColor(105, 184, 238, 175), 1.25))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class IceTitleBar(QWidget):
    """轻量标题栏：可拖动窗口，并提供关闭按钮。"""

    HEIGHT = 34

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.drag_offset = QPoint()
        self.setObjectName("iceTitleBar")
        self.setFixedHeight(self.HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 4, 3)
        layout.setSpacing(6)

        self.title = QLabel(dialog.windowTitle(), self)
        self.title.setObjectName("iceTitleText")
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title, 1)

        self.close_button = QPushButton("×", self)
        self.close_button.setObjectName("iceCloseButton")
        self.close_button.setToolTip("关闭")
        self.close_button.clicked.connect(dialog.close)
        layout.addWidget(self.close_button)

    def sync_title(self):
        self.title.setText(self.dialog.windowTitle())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.dialog.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            self.drag_offset = (
                event.globalPosition().toPoint() - self.dialog.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and not self.drag_offset.isNull()
        ):
            self.dialog.move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_offset = QPoint()
        super().mouseReleaseEvent(event)


class IceGlassTheme(QObject):
    """把背景和统一按钮状态应用到所有顶层 QDialog。"""

    _PRIMARY_COLORS = (
        "#3f51b5", "#4caf50", "#2196f3", "#009de5",
        "#00dbde", "#da73eb", "#7e57c2", "#ff9800",
    )
    _DANGER_COLORS = ("#ff4c4c", "#e53935", "color: red", "color:red")

    def __init__(self, app: QApplication, background_path: str):
        super().__init__(app)
        self.app = app
        self.background_path = os.path.abspath(background_path)
        self.background = QPixmap(self.background_path)

    def eventFilter(self, watched, event):
        if isinstance(watched, QDialog) and watched.isWindow():
            if event.type() == QEvent.Type.Polish:
                self._prepare_dialog(watched)
            elif event.type() == QEvent.Type.Show:
                self._prepare_dialog(watched)
                self._paint_background(watched)
            elif event.type() == QEvent.Type.Resize:
                self._paint_background(watched)
            elif event.type() == QEvent.Type.WindowTitleChange:
                title_bar = getattr(watched, "_ice_title_bar", None)
                if title_bar is not None:
                    title_bar.sync_title()
        return super().eventFilter(watched, event)

    def _prepare_dialog(self, dialog: QDialog):
        if dialog.property("_iceThemePrepared"):
            return
        dialog.setProperty("_iceThemePrepared", True)
        dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        dialog.setAutoFillBackground(False)
        dialog.setContentsMargins(8, IceTitleBar.HEIGHT + 5, 8, 8)

        background = IceBackgroundWidget(dialog, self.background)
        background.lower()
        dialog._ice_background_widget = background

        title_bar = IceTitleBar(dialog)
        title_bar.raise_()
        dialog._ice_title_bar = title_bar

        # 无边框窗口失去了 Windows 自带的缩放边框。右下角保留一个系统
        # QSizeGrip，使阅读器和日历等窗口仍可任意拖大、拖小。
        resize_grip = QSizeGrip(dialog)
        resize_grip.setToolTip("拖动调整窗口大小")
        resize_grip.resize(22, 22)
        resize_grip.raise_()
        dialog._ice_resize_grip = resize_grip

        for button in dialog.findChildren(QPushButton):
            if button is title_bar.close_button:
                continue
            if b"theDate" in button.dynamicPropertyNames():
                continue
            inline = (button.styleSheet() or "").lower()
            if any(color in inline for color in self._DANGER_COLORS):
                button.setProperty("uiRole", "danger")
            elif any(color in inline for color in self._PRIMARY_COLORS):
                button.setProperty("uiRole", "primary")
            elif "border:none" in inline.replace(" ", "") or "border: none" in inline:
                button.setProperty("uiRole", "quiet")

            if inline:
                button.setStyleSheet("")
            button.style().unpolish(button)
            button.style().polish(button)

        for list_widget in dialog.findChildren(QListWidget):
            inline = (list_widget.styleSheet() or "").lower()
            if "background" in inline or "border" in inline:
                list_widget.setStyleSheet("")

    def _paint_background(self, dialog: QDialog):
        if dialog.width() <= 0 or dialog.height() <= 0:
            return

        # 不只把图片画成圆角，还把 Windows 窗口本身裁成圆角。
        # 四个角不再属于窗口区域，会直接显示后面的桌面。
        window_path = QPainterPath()
        window_path.addRoundedRect(QRectF(dialog.rect()), 18, 18)
        dialog.setMask(QRegion(window_path.toFillPolygon().toPolygon()))
        background = getattr(dialog, "_ice_background_widget", None)
        if background is not None:
            background.setGeometry(dialog.rect())
            background.lower()
        title_bar = getattr(dialog, "_ice_title_bar", None)
        if title_bar is not None:
            title_bar.setGeometry(8, 3, max(1, dialog.width() - 16), IceTitleBar.HEIGHT)
            title_bar.raise_()
        resize_grip = getattr(dialog, "_ice_resize_grip", None)
        if resize_grip is not None:
            resize_grip.setGeometry(
                max(0, dialog.width() - 28), max(0, dialog.height() - 28), 20, 20)
            resize_grip.raise_()
        dialog.update()


def install_ice_glass_theme(app: QApplication, background_path: str):
    """安装一次主题并返回持有生命周期的主题对象。"""
    existing = getattr(app, "_giegisa_ice_theme", None)
    if existing is not None:
        return existing

    app.setStyleSheet(ICE_GLASS_QSS)
    theme = IceGlassTheme(app, background_path)
    app.installEventFilter(theme)
    app._giegisa_ice_theme = theme
    return theme
