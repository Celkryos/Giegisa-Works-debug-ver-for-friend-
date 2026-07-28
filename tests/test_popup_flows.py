"""bug 清单端到端流程回归测试（offscreen）。

逐条对应 260728-桌宠现有bug.txt 中修复的场景：
1. 待办删除确认（bug 1）——确认框非模态，不再冻结/遮挡日程面板
2. 打卡删除确认（bug 3-3）
3. 便签移动分组（bug 3-1，原 setCurrentIndex 闪退点）
4. 便签新建分组（bug 3-2）
5. 记忆档案快捷清理：固定天数与自定义天数（bug 3-5/3-6）
6. 记忆档案收藏记录（favorite_record 与便签移动同源的闪退点）
"""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton, QWidget

import oc
import core.calendar_service as calendar_service_module
import dialogs.notes as notes_module
from dialogs.library import HistoryDialog
from dialogs.notes import NotesManagerDialog


class FakeChatThread:
    def __init__(self, history):
        self.history = history
        self.saved = 0

    def save_history(self):
        self.saved += 1

    def delete_history_item(self, pair_index):
        del self.history[pair_index * 2: pair_index * 2 + 2]


class FakePet(QWidget):
    def __init__(self):
        super().__init__()
        self.config = json.loads(json.dumps(oc.DEFAULT_CONFIG))
        self.config["note_folders"] = ["默认便签", "工作"]
        self.config["notes"] = [{
            "id": "n1", "time": "2026-07-25 12:00", "text": "测试便签",
            "status": "active", "folder": "默认便签",
            "pinned": False, "locked": False}]
        self.config["schedules"] = [{
            "id": 1, "task": "测试待办", "note": "", "time": "09:00",
            "date": "2026-07-28", "repeat": "once", "repeat_days": 1,
            "category": "日待办", "status": "pending", "alarm_on": False,
            "done_dates": []}]
        self.config["checkins"] = [{
            "id": 3, "name": "喝水", "note": "", "enabled": True,
            "archived": False, "remind_times": [], "created": "2026-07-01",
            "done_dates": []}]
        old = time.time() - 10 * 86400
        self.chat_thread = FakeChatThread([
            {"role": "user", "content": "旧消息", "timestamp": old},
            {"role": "assistant", "content": "旧回复", "timestamp": old},
            {"role": "user", "content": "新消息", "timestamp": time.time()},
            {"role": "assistant", "content": "新回复", "timestamp": time.time()},
        ])
        self.calendar_service = oc.CalendarService(self.config)

    def refresh_dialogs(self, *args):
        pass

    def inject_system_event(self, *args):
        pass

    def show_bubble(self, *args, **kwargs):
        pass

    def speak_today_plan(self, *args, **kwargs):
        pass


def _click_ok(dialog):
    for button in dialog.findChildren(QPushButton):
        if button.text() == "确定":
            button.click()
            return
    raise AssertionError("弹窗里没有“确定”按钮")


def _only_popup(parent, cls=QDialog):
    """取 parent 当前唯一可见的弹窗子窗口。

    已关闭的弹窗走 WA_DeleteOnClose 延迟销毁，findChild 可能先命中
    这些“僵尸”窗口，因此先跑一轮事件循环再按可见性过滤。
    """
    app = QApplication.instance()
    app.processEvents()
    popups = [p for p in parent.findChildren(cls) if p.isVisible()]
    assert len(popups) == 1, popups
    return popups[0]


def _assert_modeless_child(popup, parent):
    assert popup is not None, "没有弹出子窗口"
    assert not popup.isModal()
    assert popup.windowModality() == Qt.WindowModality.NonModal
    assert parent.isEnabled(), "父面板被冻结（窗口阻滞复发）"
    assert QApplication.activeModalWidget() is None


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    old_notes_saver = notes_module.save_config
    old_service_saver = calendar_service_module.save_config
    notes_module.save_config = lambda *args, **kwargs: True
    calendar_service_module.save_config = lambda *args, **kwargs: True
    try:
        pet = FakePet()
        pet.show()

        # ---- bug 1：待办删除确认 ----
        schedule_dlg = oc.ScheduleDialog(pet.calendar_service, pet)
        schedule_dlg.show()
        schedule_dlg.del_task(pet.config["schedules"][0])
        box = _only_popup(schedule_dlg, QMessageBox)
        _assert_modeless_child(box, schedule_dlg)
        box.button(QMessageBox.StandardButton.Yes).click()
        assert pet.config["schedules"] == [], "待办未被删除"

        # ---- bug 3-3：打卡删除确认 ----
        checkin_dlg = oc.CheckinDialog(pet.calendar_service, pet)
        checkin_dlg.show()
        checkin_dlg.delete(pet.config["checkins"][0])
        box = _only_popup(checkin_dlg, QMessageBox)
        _assert_modeless_child(box, checkin_dlg)
        box.button(QMessageBox.StandardButton.No).click()
        assert len(pet.config["checkins"]) == 1, "打卡项被误删"
        checkin_dlg.delete(pet.config["checkins"][0])
        box = _only_popup(checkin_dlg, QMessageBox)
        box.button(QMessageBox.StandardButton.Yes).click()
        assert pet.config["checkins"] == [], "打卡项未被删除"

        # ---- bug 3-1：便签移动（原闪退点）----
        notes_dlg = NotesManagerDialog(pet)
        notes_dlg.show()
        note = pet.config["notes"][0]
        notes_dlg.move_note(note)
        popup = _only_popup(notes_dlg)
        _assert_modeless_child(popup, notes_dlg)
        popup.editor.setCurrentIndex(1)  # “工作”
        _click_ok(popup)
        assert note["folder"] == "工作", note
        # 成功提示同样非模态
        info = _only_popup(notes_dlg, QMessageBox)
        _assert_modeless_child(info, notes_dlg)
        info.button(QMessageBox.StandardButton.Ok).click()

        # ---- bug 3-2：便签新建分组 ----
        notes_dlg.new_folder()
        popup = _only_popup(notes_dlg)
        _assert_modeless_child(popup, notes_dlg)
        popup.editor.setText("灵感")
        _click_ok(popup)
        assert "灵感" in pet.config["note_folders"]

        # ---- bug 3-5/3-6：记忆档案快捷清理 ----
        history_dlg = HistoryDialog(pet)
        history_dlg.show()
        history_dlg.execute_quick_delete(7)  # 删除 1 周前
        info = _only_popup(history_dlg, QMessageBox)
        _assert_modeless_child(info, history_dlg)
        info.button(QMessageBox.StandardButton.Ok).click()
        assert len(pet.chat_thread.history) == 2, pet.chat_thread.history
        assert pet.chat_thread.history[0]["content"] == "新消息"

        history_dlg.execute_quick_delete(-1)  # 自定义天数
        popup = _only_popup(history_dlg)
        _assert_modeless_child(popup, history_dlg)
        popup.editor.setText("0")  # 0 = 清空全部（未锁定）
        _click_ok(popup)
        assert pet.chat_thread.history == [], pet.chat_thread.history
        info = _only_popup(history_dlg, QMessageBox)
        info.button(QMessageBox.StandardButton.Ok).click()

        # ---- favorite_record：与便签移动同源的 setCurrentIndex 闪退点 ----
        pet.chat_thread.history.extend([
            {"role": "user", "content": "问", "timestamp": time.time()},
            {"role": "assistant", "content": "答", "timestamp": time.time()},
        ])
        history_dlg.favorite_record(0)
        popup = _only_popup(history_dlg)
        _assert_modeless_child(popup, history_dlg)
        _click_ok(popup)  # 默认选中“默认收藏夹”
        favorites = pet.config["favorite_folders"]["默认收藏夹"]
        assert [m["content"] for m in favorites] == ["问", "答"], favorites

        app.processEvents()
    finally:
        notes_module.save_config = old_notes_saver
        calendar_service_module.save_config = old_service_saver
    print("POPUP_FLOWS_OK")


if __name__ == "__main__":
    main()
