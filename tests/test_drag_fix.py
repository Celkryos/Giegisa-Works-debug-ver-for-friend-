"""桌宠位移 bug 回归测试（合成鼠标事件）。

旧缺陷：
1. is_following 按下后永不复位 → 之后任何移动都拿陈旧 drag_pos 移动窗口
2. mouseMoveEvent 写成 `Qt.MouseButton.LeftButton and ...`（常量恒真）
3. 打字 resize 的锚定位移与拖拽打架
症状：说话时右键/普通移动有概率触发大幅位移、坐标飘动。
"""
import json
import os
import sys
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

import oc
import core.calendar_service as calendar_service_module
import dialogs.ebook as ebook_dialog_module
from ui.widgets import ImageBubble


def _event(etype, local, button, buttons):
    local = QPointF(local)
    return QMouseEvent(etype, local, QPointF(1000, 1000) + local,
                       button, buttons, Qt.KeyboardModifier.NoModifier)


def _press_move_release(widget):
    """完整走一遍 左键按下→拖动→松开→悬空/右键移动，返回各阶段坐标。"""
    widget.move(500, 500)
    # 1. 左键按下并拖动：窗口应跟随
    widget.mousePressEvent(_event(QMouseEvent.Type.MouseButtonPress,
                                  QPoint(10, 10), Qt.MouseButton.LeftButton,
                                  Qt.MouseButton.LeftButton))
    widget.mouseMoveEvent(_event(QMouseEvent.Type.MouseMove,
                                 QPoint(60, 70), Qt.MouseButton.NoButton,
                                 Qt.MouseButton.LeftButton))
    after_drag = widget.pos()
    assert after_drag == QPoint(550, 560), after_drag
    # 2. 松开：is_following 必须复位
    widget.mouseReleaseEvent(_event(QMouseEvent.Type.MouseButtonRelease,
                                    QPoint(60, 70), Qt.MouseButton.LeftButton,
                                    Qt.MouseButton.NoButton))
    assert not widget.is_following
    # 3. 松开后的悬空移动（无按键）：窗口绝不能再动（旧 bug 会“吸”过去）
    widget.mouseMoveEvent(_event(QMouseEvent.Type.MouseMove,
                                 QPoint(300, 300), Qt.MouseButton.NoButton,
                                 Qt.MouseButton.NoButton))
    assert widget.pos() == after_drag, widget.pos()
    # 4. 右键拖动：同样不得移动窗口
    widget.mouseMoveEvent(_event(QMouseEvent.Type.MouseMove,
                                 QPoint(320, 320), Qt.MouseButton.NoButton,
                                 Qt.MouseButton.RightButton))
    assert widget.pos() == after_drag, widget.pos()
    # 5. 再次左键拖拽：仍应正常工作
    widget.mousePressEvent(_event(QMouseEvent.Type.MouseButtonPress,
                                  QPoint(60, 70), Qt.MouseButton.LeftButton,
                                  Qt.MouseButton.LeftButton))
    widget.mouseMoveEvent(_event(QMouseEvent.Type.MouseMove,
                                 QPoint(80, 90), Qt.MouseButton.NoButton,
                                 Qt.MouseButton.LeftButton))
    assert widget.pos() == QPoint(570, 580), widget.pos()
    widget.mouseReleaseEvent(_event(QMouseEvent.Type.MouseButtonRelease,
                                    QPoint(80, 90), Qt.MouseButton.LeftButton,
                                    Qt.MouseButton.NoButton))


class _StubPet:
    def __init__(self):
        self.config = {}


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    # ---- ImageBubble（与桌宠本体同型的拖拽逻辑）----
    bubble = ImageBubble(_StubPet())
    bubble.show()
    _press_move_release(bubble)
    bubble.close()

    # ---- DesktopPet 本体 ----
    old_loader = oc.load_config
    old_saver = oc.save_config
    old_service_saver = calendar_service_module.save_config
    old_ebook_cleanup = ebook_dialog_module._cleanup_pending_ebook_deletions
    fake_config = json.loads(json.dumps(oc.DEFAULT_CONFIG))
    fake_config["last_sign_in"] = date.today().strftime("%Y-%m-%d")
    oc.load_config = lambda: fake_config
    oc.save_config = lambda *args, **kwargs: True
    calendar_service_module.save_config = lambda *args, **kwargs: True
    ebook_dialog_module._cleanup_pending_ebook_deletions = lambda *args, **kwargs: None
    try:
        pet = oc.DesktopPet()
        pet.show()
        app.processEvents()
        # 打字中的 resize 锚定：拖拽期间不得顶窗口
        _press_move_release(pet)
        pet.is_following = True  # 模拟拖拽中
        old_y = pet.y()
        pet.resize(pet.width(), pet.height() + 60)
        assert pet.y() == old_y, (old_y, pet.y())
        pet.is_following = False
        pet.close()
        pet.deleteLater()
        app.processEvents()
    finally:
        oc.load_config = old_loader
        oc.save_config = old_saver
        calendar_service_module.save_config = old_service_saver
        ebook_dialog_module._cleanup_pending_ebook_deletions = old_ebook_cleanup
    print("DRAG_FIX_OK")


if __name__ == "__main__":
    main()
