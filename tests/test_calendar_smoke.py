import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QPushButton, QWidget
from PyQt6.QtCore import QPoint

import oc


class FakePet(QWidget):
    def __init__(self):
        super().__init__()
        self.config = json.loads(json.dumps(oc.DEFAULT_CONFIG))
        self.config["schedules"] = [
            {
                "id": 1,
                "task": "一次很长很长、用于检查窄窗口换行与按钮自适应的日程标题",
                "note": "说明" * 40,
                "time": "09:00",
                "date": "2026-07-24",
                "repeat": "once",
                "repeat_days": 1,
                "category": "日待办",
                "status": "pending",
                "alarm_on": True,
                "done_dates": [],
            },
            {
                "id": 2,
                "task": "每周日程",
                "note": "",
                "time": "10:00",
                "date": "2026-07-03",
                "repeat": "weekly",
                "repeat_days": 1,
                "category": "周待办",
                "status": "pending",
                "alarm_on": True,
                "done_dates": [],
            },
        ]
        self.config["checkins"] = [
            {
                "id": 3,
                "name": "喝水",
                "note": "",
                "enabled": True,
                "archived": False,
                "remind_times": ["09:30"],
                "created": "2026-07-01",
                "done_dates": [],
            }
        ]
        self.spoken_dates = []

    def refresh_dialogs(self, *args):
        pass

    def speak_today_plan(self, d=None):
        self.spoken_dates.append(d)

    def mark_schedule_done(self, item, d=None, done=True):
        oc.sched_set_done(item, d or date.today(), done)

    def do_checkin(self, item, d=None, done=True):
        oc.checkin_set_done(item, d or date.today(), done)

    def change_mood(self, delta):
        pass

    def inject_system_event(self, *args):
        pass

    def send_msg(self, *args, **kwargs):
        pass

    def open_dialog(self, *args):
        pass


def assert_domain_rules():
    monthly = {"date": "2026-01-31", "repeat": "monthly"}
    assert oc.sched_occurs_on(monthly, date(2026, 2, 28))
    assert not oc.sched_occurs_on(monthly, date(2026, 2, 27))

    yearly = {"date": "2024-02-29", "repeat": "yearly"}
    assert oc.sched_occurs_on(yearly, date(2025, 2, 28))

    custom = {"date": "2026-07-01", "repeat": "custom", "repeat_days": 3}
    assert oc.sched_occurs_on(custom, date(2026, 7, 4))
    assert not oc.sched_occurs_on(custom, date(2026, 7, 5))

    # 未绑定日期的待办每天到点可提醒，但不应把整个月每一天都染成“有安排”。
    general = {"date": "", "status": "pending"}
    assert general in oc.schedules_of_day({"schedules": [general]}, date.today())
    assert general not in oc.schedules_of_day(
        {"schedules": [general]}, date.today() - timedelta(days=1)
    )

    # 停用/归档的打卡不参与全勤、日历和统计。
    checkins = [
        {"name": "启用", "enabled": True, "archived": False},
        {"name": "停用", "enabled": False, "archived": False},
        {"name": "归档", "enabled": True, "archived": True},
    ]
    assert [x["name"] for x in oc.active_checkins({"checkins": checkins})] == ["启用"]


def assert_migration_rules():
    cfg = json.loads(json.dumps(oc.DEFAULT_CONFIG))
    cfg["daily_checkins"] = [
        {"id": 11, "title": "喝水", "last_done": "2026-07-23"},
        {"title": "早睡", "last_done": ""},
    ]
    cfg["checkins"] = [
        {
            "id": 12,
            "name": "已有项目",
            "enabled": True,
            "archived": False,
            "remind_times": [],
            "created": "2026-07-01",
            "done_dates": [],
        }
    ]
    oc.migrate_config(cfg)
    assert {x["name"] for x in cfg["checkins"]} == {"已有项目", "喝水", "早睡"}
    oc.migrate_config(cfg)
    assert len(cfg["checkins"]) == 3


def assert_archive_is_lossless():
    thread = oc.ChatThread(json.loads(json.dumps(oc.DEFAULT_CONFIG)))
    thread.HISTORY_HARD_CAP = 2
    original = [
        {"role": "user", "content": "一"},
        {"role": "assistant", "content": "二"},
        {"role": "user", "content": "三"},
        {"role": "assistant", "content": "四"},
    ]
    thread.history = list(original)
    import threads.chat as chat_module
    old_writer = chat_module._atomic_write_json
    chat_module._atomic_write_json = lambda *args, **kwargs: False
    try:
        thread._archive_overflow()
    finally:
        chat_module._atomic_write_json = old_writer
    assert thread.history == original


def assert_busy_chat_is_queued():
    thread = oc.ChatThread(json.loads(json.dumps(oc.DEFAULT_CONFIG)))
    thread.isRunning = lambda: True
    thread.send_message("第二条", "状态")
    assert thread._pending_messages == [("第二条", "状态", None, "image/png")]


def main():
    assert_domain_rules()
    assert_migration_rules()
    assert_archive_is_lossless()
    assert_busy_chat_is_queued()
    app = QApplication.instance() or QApplication(sys.argv)
    oc.install_ice_glass_theme(app, oc.UI_BACKGROUND_FILE)
    pet = FakePet()
    dialogs = [
        oc.EditScheduleDialog(pet),
        oc.EditCheckinDialog(pet),
        oc.ScheduleDialog(pet),
        oc.DayDetailDialog(pet, date(2026, 7, 24)),
        oc.MiniCalendarDialog(pet),
        oc.CheckinDialog(pet),
        oc.StatsDialog(pet),
    ]
    for dialog in dialogs:
        dialog.show()
        app.processEvents()
        hint = dialog.sizeHint()
        print(
            dialog.__class__.__name__,
            f"size={dialog.width()}x{dialog.height()}",
            f"hint={hint.width()}x{hint.height()}",
        )
        assert dialog.width() > 0 and dialog.height() > 0
        assert hasattr(dialog, "_ice_resize_grip")
        assert dialog._ice_resize_grip.isVisible()
        for list_name in ("list_widget", "day_list"):
            list_widget = getattr(dialog, list_name, None)
            if list_widget is None or not hasattr(list_widget, "_relayout_items"):
                continue
            list_widget._relayout_items()
            if list_widget.count() and list_widget.itemWidget(list_widget.item(0)):
                item_widget = list_widget.itemWidget(list_widget.item(0))
                assert item_widget.width() >= list_widget.viewport().width() - 14
                assert list_widget.item(0).sizeHint().height() >= item_widget.sizeHint().height()
                for button in item_widget.findChildren(QPushButton):
                    assert button.height() >= 34
                    assert button.geometry().bottom() <= item_widget.contentsRect().bottom()
        if isinstance(dialog, oc.MiniCalendarDialog):
            assert dialog.width() >= hint.width()
            cell = dialog.cells[0][2]
            assert cell.sizeHint().width() <= cell.width()
            assert cell.height() >= cell.fontMetrics().height() + 4
            rounded_mask = dialog.mask()
            assert not rounded_mask.isEmpty()
            assert not rounded_mask.contains(QPoint(0, 0))
            assert rounded_mask.contains(dialog.rect().center())
        dialog.grab().save(f"_smoke_{dialog.__class__.__name__}.png")
        dialog.close()

    # 主桌宠也要能完整创建；用内存配置隔离，避免测试改动真实 config/history。
    old_loader = oc.load_config
    old_saver = oc.save_config
    fake_config = json.loads(json.dumps(oc.DEFAULT_CONFIG))
    fake_config["last_sign_in"] = date.today().strftime("%Y-%m-%d")
    fake_config["api_type"] = "openai"
    fake_config["gemini_proxy"] = "http://127.0.0.1:65530"
    fake_config["notes"] = [
        {
            "id": index,
            "time": "2026-07-25 12:00",
            "text": "很长的便签内容，用来验证窗口缩放后文字换行且按钮不会重叠。" * 8,
            "status": "active",
            "folder": "默认便签",
            "pinned": False,
            "locked": False,
        }
        for index in range(12)
    ]
    old_proxy_env = {
        key: os.environ.get(key)
        for key in ("HTTP_PROXY", "HTTPS_PROXY")
    }
    oc.load_config = lambda: fake_config
    oc.save_config = lambda *args, **kwargs: True
    try:
        desktop_pet = oc.DesktopPet()
        assert {
            key: os.environ.get(key)
            for key in ("HTTP_PROXY", "HTTPS_PROXY")
        } == old_proxy_env
        desktop_pet.show()
        app.processEvents()
        assert desktop_pet.chat_thread is not None
        legacy_dialogs = [
            oc.UserProfileDialog(desktop_pet),
            oc.MoodDialog(desktop_pet),
            oc.CollectionManagerDialog(desktop_pet, "collected_items", "储物盒子"),
            oc.QuickNoteDialog(desktop_pet),
            oc.NotesManagerDialog(desktop_pet),
            oc.DistractionSettingsDialog(desktop_pet),
            oc.AutoEventSettingsDialog(desktop_pet),
            oc.RandomEventDialog(
                desktop_pet,
                {"scenario": "测试", "optA": "A", "optB": "B"}),
            oc.StoreDialog(desktop_pet),
            oc.ApiSettingsDialog(desktop_pet),
            oc.AppearanceDialog(desktop_pet),
            oc.FocusDialog(desktop_pet),
            oc.MemorySettingsDialog(desktop_pet),
            oc.HistoryDialog(desktop_pet),
        ]
        # 同时打开全部面板，覆盖“窗口很多”的生命周期压力场景。
        for dialog in legacy_dialogs:
            dialog.show()
        app.processEvents()
        for dialog in legacy_dialogs:
            assert dialog.width() > 0 and dialog.height() > 0
        notes_dialog = next(d for d in legacy_dialogs if isinstance(d, oc.NotesManagerDialog))
        notes_dialog.resize(notes_dialog.minimumWidth(), notes_dialog.height())
        app.processEvents()
        assert notes_dialog.list_widget.count() == len(fake_config["notes"])
        for i in range(notes_dialog.list_widget.count()):
            item = notes_dialog.list_widget.item(i)
            widget = notes_dialog.list_widget.itemWidget(item)
            assert item.sizeHint().height() >= widget.minimumSizeHint().height()
            for button in widget.findChildren(QPushButton):
                assert button.height() >= 34
                assert button.geometry().bottom() <= widget.contentsRect().bottom()
        notes_dialog.grab().save("_smoke_NotesManagerDialog.png")

        # 多条提醒必须排队，任何时刻最多显示一条。
        desktop_pet.queue_reminder("checkin", {
            "id": "stress-1", "name": "提醒一", "done_dates": []})
        desktop_pet.queue_reminder("checkin", {
            "id": "stress-2", "name": "提醒二", "done_dates": []})
        app.processEvents()
        assert desktop_pet._active_alert is not None
        assert len(desktop_pet._alert_queue) == 1
        desktop_pet.close_all_dialogs()
        app.processEvents()
        assert desktop_pet._active_alert is None
        assert not desktop_pet._alert_queue

        for dialog in legacy_dialogs:
            dialog.close()
            dialog.deleteLater()
        legacy_dialogs.clear()
        app.processEvents()
        desktop_pet.flush_before_exit()
        desktop_pet.close()
        desktop_pet.deleteLater()
        app.processEvents()
    finally:
        oc.load_config = old_loader
        oc.save_config = old_saver
        for key, value in old_proxy_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    print("CALENDAR_SMOKE_OK")


if __name__ == "__main__":
    main()
