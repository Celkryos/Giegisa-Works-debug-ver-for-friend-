"""气泡布局与系统提示回归测试。

覆盖网友反馈的三点：
1. 气泡文字增长时桌宠图像位置骤然偏移 → 锚定后图像屏幕坐标恒定
2. 文字过长显示不全 → 窗口夹回屏幕内 + 超长回复拆成连续气泡
3. API 卡顿提示显性气泡挤掉正式回答 → 改回静默（写历史不弹气泡）
"""
import json
import os
import sys
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication

import oc
import core.calendar_service as calendar_service_module
import dialogs.ebook as ebook_dialog_module


class _FakeChatThread:
    def __init__(self):
        self.history = []

    def save_history(self):
        pass


def _image_anchor(pet):
    """桌宠图像在屏幕上的“底边中点”坐标。"""
    label = pet.pet_label
    center = label.mapToGlobal(label.rect().center())
    bottom = label.mapToGlobal(label.rect().bottomLeft()).y()
    return center.x(), bottom


def main():
    app = QApplication.instance() or QApplication(sys.argv)

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

        # ---- 1. 锚定：气泡从无到有、从短到长，图像坐标不动 ----
        pet.move(500, 300)
        before = _image_anchor(pet)
        pet.chat_bubble.setText("短气泡")
        pet.chat_bubble.show()
        pet.adjustSize()
        app.processEvents()
        mid = _image_anchor(pet)
        pet.chat_bubble.setText("很长的气泡内容，" * 30)
        pet.adjustSize()
        app.processEvents()
        after = _image_anchor(pet)
        for a, b in ((before, mid), (mid, after)):
            assert abs(a[0] - b[0]) <= 2, (a, b)
            assert abs(a[1] - b[1]) <= 2, (a, b)

        # ---- 2. 夹持：贴屏幕顶部时，超高气泡也不顶出屏幕 ----
        pet.move(500, 0)
        pet.chat_bubble.setText("顶部长文本，" * 60)
        pet.adjustSize()
        app.processEvents()
        avail = app.primaryScreen().availableGeometry()
        assert pet.y() >= avail.top(), (pet.y(), avail.top())

        pet.chat_bubble.hide()
        pet.adjustSize()
        app.processEvents()

        # ---- 3. 超长回复拆分为连续气泡 ----
        pet.chat_thread = _FakeChatThread()
        long_reply = "【normal】" + "这是一段很长的回答。" * 120
        pet.handle_api_reply(long_reply)
        assert pet.is_typing
        assert len(pet.full_text) <= oc._BUBBLE_SPLIT_LEN, len(pet.full_text)
        assert len(pet._bubble_queue) >= 1, "超长回复没有拆出后续气泡"
        # 拼接还原：所有文字都在（忽略切分处的空白差异）
        joined = "".join([pet.full_text] + [t for t, _ in pet._bubble_queue])
        assert "这是一段很长的回答。" * 120 == joined.replace(" ", ""), len(joined)
        pet.type_timer.stop()
        pet.is_typing = False
        pet._bubble_queue.clear()
        pet.chat_bubble.hide()

        # ---- 4. API 卡顿提示静默：写历史、不弹气泡、不挤掉回答 ----
        pet.handle_api_lag(12.34)
        assert len(pet.chat_thread.history) == 2
        assert "卡顿" in pet.chat_thread.history[0]["content"]
        assert "12.3" in pet.chat_thread.history[1]["content"]
        assert not pet.chat_bubble.isVisible(), "卡顿提示不应弹出气泡"
        assert not pet.is_typing, "卡顿提示不应打断打字状态"
        assert not pet._bubble_queue, "卡顿提示不应进入气泡队列"

        # 普通系统事件仍应弹气泡（行为不回归）
        pet.inject_system_event("系统：测试事件", "【normal】正常提示")
        assert pet.is_typing or pet.chat_bubble.isVisible()
        pet.type_timer.stop()
        pet.is_typing = False
        pet._bubble_queue.clear()

        pet.close()
        pet.deleteLater()
        app.processEvents()
    finally:
        oc.load_config = old_loader
        oc.save_config = old_saver
        calendar_service_module.save_config = old_service_saver
        ebook_dialog_module._cleanup_pending_ebook_deletions = old_ebook_cleanup

    # ---- 5. 拆分函数单元行为 ----
    assert oc._split_bubble_text("") == []
    assert oc._split_bubble_text("短") == ["短"]
    text = "第一句。" * 200
    chunks = oc._split_bubble_text(text)
    assert all(len(c) <= oc._BUBBLE_SPLIT_LEN for c in chunks)
    assert "".join(chunks) == text
    assert all(c.endswith("。") for c in chunks[:-1]), "应优先在句末断开"
    hard = "无标点" * 300
    hard_chunks = oc._split_bubble_text(hard)
    assert all(len(c) <= oc._BUBBLE_SPLIT_LEN for c in hard_chunks)
    assert "".join(hard_chunks) == hard

    print("BUBBLE_LAYOUT_OK")


if __name__ == "__main__":
    main()
