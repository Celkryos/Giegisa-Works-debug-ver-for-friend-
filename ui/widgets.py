import os
import re
from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout, QDialog, QListWidget, QPushButton, QTextEdit, QSizePolicy)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QSize
from PyQt6.QtGui import QPixmap

class ImageBubble(QWidget):
    def __init__(self, parent_pet):
        super().__init__()
        self.pet = parent_pet
        # 设为无边框、工具窗口、悬浮置顶
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.layout = QVBoxLayout(self)
        
        self.img_label = QLabel("正在解析异世界图像数据...")
        self.img_label.setStyleSheet(f"background-color: {self.pet.config.get('bubble_bg', 'rgba(255,255,255,220)')}; border-radius: 10px; border: 2px solid {self.pet.config.get('bubble_border', '#555')}; padding: 10px; font-weight: bold;")
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.close_btn = QPushButton("✖")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setStyleSheet("background-color: #ff4c4c; color: white; border-radius: 12px; font-weight: bold; font-family: 'Microsoft YaHei';")
        self.close_btn.clicked.connect(self.close)
        
        top_layout = QHBoxLayout()
        top_layout.addStretch()
        top_layout.addWidget(self.close_btn)
        
        self.layout.addLayout(top_layout)
        self.layout.addWidget(self.img_label)
        
        self.is_following = False
        self.mouse_drag_pos = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_following = True
            self.mouse_drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_following and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self.mouse_drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        # 松开即复位拖拽状态，避免陈旧的 mouse_drag_pos 把窗口“吸”走。
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_following = False
        super().mouseReleaseEvent(event)

    def load_image(self, data):
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if not pixmap.isNull():
            # 限制最大宽高防溢出
            if pixmap.width() > 350 or pixmap.height() > 350:
                pixmap = pixmap.scaled(350, 350, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.img_label.setPixmap(pixmap)
            self.adjustSize()
        else:
            self.img_label.setText("【图像数据损坏，渲染失败】")

class ResponsiveListWidget(QListWidget):
    """让自定义列表项先按视口宽度换行，再计算正确高度。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._relayout_pending = False

    def schedule_relayout(self):
        if self._relayout_pending:
            return
        self._relayout_pending = True
        QTimer.singleShot(0, self._relayout_items)

    def _relayout_items(self):
        self._relayout_pending = False
        width = max(120, self.viewport().width() - 10)
        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            if not widget:
                continue
            widget.setMinimumWidth(width)
            widget.setMaximumWidth(width)
            layout = widget.layout()
            if layout:
                layout.invalidate()
                layout.activate()
                height = layout.heightForWidth(width)
            else:
                height = widget.sizeHint().height()
            # Qt 在自定义 QListWidgetItem 首次测量时经常漏算按钮边框与布局间距，
            # 尤其在 125%/150% DPI 下会把最下面一排按钮裁掉。保留一段明确的
            # 垂直安全区，并在设置 item 高度前重新激活布局。
            widget.adjustSize()
            height = max(
                widget.minimumSizeHint().height(), widget.sizeHint().height(),
                height if height >= 0 else 0, 38) + 14
            widget.resize(width, height)
            item.setSizeHint(QSize(width, height))
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.schedule_relayout()

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_relayout()

    def setItemWidget(self, item, widget):
        super().setItemWidget(item, widget)
        self.schedule_relayout()

class DraggableListWidget(ResponsiveListWidget):
    order_updated = pyqtSignal(list)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        
    def dropEvent(self, event):
        super().dropEvent(event)
        new_order = []
        for i in range(self.count()):
            item = self.item(i)
            new_order.append(item.data(Qt.ItemDataRole.UserRole))
        self.order_updated.emit(new_order)

class ChatInputBox(QTextEdit):
    returnPressed = pyqtSignal()
    image_pasted = pyqtSignal()   # 粘贴了图片时通知主界面更新提示
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("与Giegisa对话... (Ctrl+v贴图，Shift+回车换行，回车发送)")
        self.setStyleSheet("background-color: rgba(255, 255, 255, 180); border: 1px solid gray; border-radius: 5px; font-family: 'Microsoft YaHei'; font-size: 13px; padding: 4px;")
        self.setFixedHeight(32)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textChanged.connect(self.adjust_height)
        # 待发送的图片（base64 文本 + 类型），发送后会清空
        self.pending_image_b64 = None
        self.pending_image_mime = "image/png"

    def adjust_height(self):
        doc_height = int(self.document().size().height())
        new_height = max(32, min(doc_height + 12, 120))
        self.setFixedHeight(new_height)
        if new_height == 120:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    # ---- 图片粘贴支持 ----
    def canInsertFromMimeData(self, source):
        if source.hasImage():
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        # 优先处理图片：不把图片塞进文本框，而是暂存起来等待随文字一起发送
        image = None
        if source.hasImage():
            image = source.imageData()
        elif source.hasUrls():
            for u in source.urls():
                if u.isLocalFile() and u.toLocalFile().lower().endswith(
                        (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif")):
                    image = QImage(u.toLocalFile())
                    break
        if image is not None and not QImage(image).isNull():
            self._store_image(QImage(image))
            return
        super().insertFromMimeData(source)

    def _store_image(self, qimage):
        try:
            # 太大的图先缩小，避免编码后体积爆炸、请求超时
            if qimage.width() > 1024 or qimage.height() > 1024:
                qimage = qimage.scaled(1024, 1024, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            qimage.save(buf, "PNG")
            buf.close()
            self.pending_image_b64 = base64.b64encode(bytes(ba)).decode("ascii")
            self.pending_image_mime = "image/png"
            self.image_pasted.emit()
        except Exception:
            self.pending_image_b64 = None

    def clear_pending_image(self):
        self.pending_image_b64 = None

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.returnPressed.emit()
        else:
            super().keyPressEvent(event)

class FocusOverlay(QWidget):
    def __init__(self, pet):
        super().__init__()
        self.pet = pet
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.label = QLabel("Focus Mode")
        self.label.setStyleSheet("background-color: rgba(20, 20, 25, 220); color: #25f8ff; padding: 10px; border-radius: 8px; font-family: 'Microsoft YaHei'; font-size: 13px; font-weight: bold; border: 2px solid #25f8ff;")
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.layout.addWidget(self.label)
        
        self.is_following = False
        self.mouse_drag_pos = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_following = True
            self.mouse_drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_following and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self.mouse_drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        # 松开即复位拖拽状态，避免陈旧的 mouse_drag_pos 把窗口“吸”走。
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_following = False
        super().mouseReleaseEvent(event)

    def update_display(self):
        if not self.pet.is_focus_mode:
            self.hide()
            return
            
        rem = self.pet.focus_seconds
        m, s = divmod(rem, 60)
        h, m = divmod(m, 60)
        time_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
        
        if self.pet.focus_type == "pomodoro":
            state_str = "🍅 工作中" if self.pet.focus_state == "work" else "☕ 休息中"
            color = "#FF3366" if self.pet.focus_state == "work" else "#00FF41"
            info = f"<font color='{color}'>{state_str}</font> (组: {self.pet.focus_sets_done+1}/{self.pet.focus_sets_total})<br>剩余: {time_str}"
        elif self.pet.focus_type == "stopwatch":
            info = f"⏳ 正计时中<br>已专注: {time_str}"
        else:
            info = f"⏱️ 倒计时中<br>剩余: {time_str}"
            
        st = self.pet.focus_start_dt.strftime('%H:%M:%S')
        et = self.pet.focus_end_dt.strftime('%H:%M:%S') if self.pet.focus_end_dt else "无限制"
        self.label.setText(f"{info}<br><font color='#AAAAAA' size='2'>起: {st} | 止: {et}</font>")

class InputDialog(QDialog):
    """【新增】公用单行输入弹窗"""
    def __init__(self, title, label_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(300, 100)
        self.layout = QVBoxLayout(self)
        
        self.layout.addWidget(QLabel(label_text))
        self.input = QLineEdit()
        self.layout.addWidget(self.input)
        
        btn = QPushButton("确定")
        btn.clicked.connect(self.accept)
        self.layout.addWidget(btn)
        
    def get_text(self):
        return self.input.text().strip()
