"""CalendarService 业务逻辑单测。不需要 Qt GUI。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from datetime import date, timedelta
from core.calendar_service import CalendarService, MILESTONES


@pytest.fixture
def empty_config():
    return {"schedules": [], "checkins": [], "coins": 0, "stats": {}}


@pytest.fixture
def service(empty_config, monkeypatch):
    # 避免测试中的存档写入覆盖真实的 config.json
    monkeypatch.setattr("core.calendar_service.save_config", lambda config, force=True: None)
    return CalendarService(empty_config)


class TestScheduleWrite:
    def test_add_schedule_returns_id_and_appends(self, service, empty_config):
        sid = service.add_schedule({
            "task": "测试待办", "time": "09:00", "category": "日待办"
        })
        assert isinstance(sid, int)
        assert sid > 0
        assert len(empty_config["schedules"]) == 1
        s = empty_config["schedules"][0]
        assert s["id"] == sid
        assert s["task"] == "测试待办"
        assert s["status"] == "pending"

    def test_add_schedule_fills_defaults(self, service, empty_config):
        service.add_schedule({"task": "minimal"})
        s = empty_config["schedules"][0]
        assert s["alarm_on"] is True
        assert s["done_dates"] == []
        assert s["repeat"] == "once"

    def test_add_schedule_emits_signals(self, service):
        signals = []
        service.schedule_added.connect(lambda sid: signals.append(("added", sid)))
        service.schedules_changed.connect(lambda: signals.append("changed"))
        sid = service.add_schedule({"task": "test"})
        # Signal 携带 str(sid)（Qt 信号类型约束），sid 本身是 int
        assert ("added", str(sid)) in signals
        assert "changed" in signals

    def test_update_schedule_modifies_fields(self, service, empty_config):
        sid = service.add_schedule({"task": "原始"})
        s = empty_config["schedules"][0]
        service.update_schedule(s, {"task": "修改后", "time": "14:00"})
        assert s["task"] == "修改后"
        assert s["time"] == "14:00"
        assert s["notified"] is False  # 改过时间后重置提醒

    def test_update_schedule_emits_signal(self, service, empty_config):
        sid = service.add_schedule({"task": "原始"})
        updated_id = []
        service.schedule_updated.connect(lambda i: updated_id.append(i))
        service.update_schedule(empty_config["schedules"][0], {"task": "改"})
        # Signal 携带 str(sid)
        assert updated_id == [str(sid)]

    def test_delete_schedule_removes_by_id(self, service, empty_config):
        sid1 = service.add_schedule({"task": "A"})
        sid2 = service.add_schedule({"task": "B"})
        assert len(empty_config["schedules"]) == 2
        service.delete_schedule(sid1)
        assert len(empty_config["schedules"]) == 1
        assert empty_config["schedules"][0]["id"] == sid2

    def test_delete_schedule_emits_signal(self, service, empty_config):
        sid = service.add_schedule({"task": "A"})
        removed = []
        service.schedule_removed.connect(lambda i: removed.append(i))
        service.delete_schedule(sid)
        # Signal 携带 str(sid)
        assert removed == [str(sid)]

    def test_mark_done_awards_20_coins(self, service, empty_config):
        service.add_schedule({"task": "测试"})
        s = empty_config["schedules"][0]
        changed = service.mark_schedule_done(s, date.today(), True)
        assert changed is True
        assert empty_config["coins"] == 20
        assert empty_config["stats"]["todo_done_total"] == 1

    def test_mark_done_then_undo_reclaims_coins(self, service, empty_config):
        service.add_schedule({"task": "测试"})
        s = empty_config["schedules"][0]
        service.mark_schedule_done(s, date.today(), True)
        service.mark_schedule_done(s, date.today(), False)
        assert empty_config["coins"] == 0
        assert empty_config["stats"]["todo_done_total"] == 0

    def test_mark_done_idempotent(self, service, empty_config):
        service.add_schedule({"task": "测试"})
        s = empty_config["schedules"][0]
        assert service.mark_schedule_done(s, date.today(), True) is True
        assert service.mark_schedule_done(s, date.today(), True) is False
        assert empty_config["coins"] == 20  # 只加一次

    def test_mark_done_emits_coins_changed(self, service, empty_config):
        service.add_schedule({"task": "测试"})
        amounts = []
        service.coins_changed.connect(lambda a: amounts.append(a))
        service.mark_schedule_done(empty_config["schedules"][0], date.today(), True)
        assert amounts == [20]

    def test_mark_done_emits_ai_speech(self, service, empty_config):
        """mark_schedule_done(done=True) 应发射 ai_speech_needed。"""
        service.add_schedule({"task": "测试语音"})
        speeches = []
        service.ai_speech_needed.connect(lambda action, reply: speeches.append((action, reply)))
        service.mark_schedule_done(empty_config["schedules"][0], date.today(), True)
        assert len(speeches) == 1
        assert "测试语音" in speeches[0][1]
        assert "20" in speeches[0][1]  # 20 数据碎片

    def test_milestone_at_100_todo(self, service, empty_config):
        empty_config["stats"]["todo_done_total"] = 99
        empty_config["stats"]["milestone_todo"] = 50
        service.add_schedule({"task": "第100个"})
        service.mark_schedule_done(empty_config["schedules"][0], date.today(), True)
        # 20 基础金币 + int(50 + 100 * 0.5) = 100 里程碑奖励 = 120
        assert empty_config["coins"] == 120
        assert empty_config["stats"]["milestone_todo"] == 100

    def test_milestone_emits_signal(self, service, empty_config):
        """验证里程碑到达时发射 milestone_reached 信号。"""
        empty_config["stats"]["todo_done_total"] = 199
        empty_config["stats"]["milestone_todo"] = 100
        service.add_schedule({"task": "第200个"})
        milestones = []
        service.milestone_reached.connect(lambda label, count: milestones.append((label, count)))
        service.mark_schedule_done(empty_config["schedules"][0], date.today(), True)
        assert ("待办", 200) in milestones

    def test_milestone_not_triggered_when_below_threshold(self, service, empty_config):
        empty_config["stats"]["todo_done_total"] = 5
        empty_config["stats"]["milestone_todo"] = 0
        service.add_schedule({"task": "第6个"})
        service.mark_schedule_done(empty_config["schedules"][0], date.today(), True)
        assert empty_config["stats"].get("milestone_todo", 0) == 0  # 不到10不触发


class TestCheckinWrite:
    def test_add_checkin(self, service, empty_config):
        cid = service.add_checkin({"name": "喝水", "remind_times": ["09:00"]})
        assert isinstance(cid, int)
        assert len(empty_config["checkins"]) == 1
        assert empty_config["checkins"][0]["name"] == "喝水"

    def test_update_checkin(self, service, empty_config):
        cid = service.add_checkin({"name": "喝水"})
        service.update_checkin(empty_config["checkins"][0], {"name": "多喝水"})
        assert empty_config["checkins"][0]["name"] == "多喝水"

    def test_delete_checkin(self, service, empty_config):
        cid = service.add_checkin({"name": "喝水"})
        service.delete_checkin(cid)
        assert len(empty_config["checkins"]) == 0

    def test_do_checkin_awards_5_coins(self, service, empty_config):
        service.add_checkin({"name": "喝水", "enabled": True})
        c = empty_config["checkins"][0]
        service.do_checkin(c, date.today(), True, quiet=True)
        assert empty_config["coins"] == 5
        assert empty_config["stats"]["checkin_done_total"] == 1

    def test_do_checkin_undo(self, service, empty_config):
        service.add_checkin({"name": "喝水", "enabled": True})
        c = empty_config["checkins"][0]
        service.do_checkin(c, date.today(), True, quiet=True)
        service.do_checkin(c, date.today(), False, quiet=True)
        assert empty_config["coins"] == 0

    def test_do_checkin_idempotent(self, service, empty_config):
        service.add_checkin({"name": "喝水", "enabled": True})
        c = empty_config["checkins"][0]
        assert service.do_checkin(c, date.today(), True) is True
        assert service.do_checkin(c, date.today(), True) is False

    def test_all_done_bonus_once_per_day(self, service, empty_config):
        service.add_checkin({"name": "A", "enabled": True})
        service.add_checkin({"name": "B", "enabled": True})
        bonus_signals = []
        service.checkin_bonus_earned.connect(lambda amt: bonus_signals.append(amt))
        coins_before = empty_config["coins"]
        service.do_checkin(empty_config["checkins"][0], date.today(), True)
        service.do_checkin(empty_config["checkins"][1], date.today(), True)
        # 应包含 5+5 (打卡) + bonus (30-60)
        assert empty_config["coins"] >= coins_before + 40
        # 验证全勤奖励已记录并发射信号
        assert empty_config.get("checkin_last_bonus_date") == date.today().strftime("%Y-%m-%d")
        assert len(bonus_signals) == 1
        assert 30 <= bonus_signals[0] <= 60

    def test_all_done_bonus_not_double_counted(self, service, empty_config):
        service.add_checkin({"name": "A", "enabled": True})
        service.do_checkin(empty_config["checkins"][0], date.today(), True)
        coins_after_first = empty_config["coins"]
        # Undo and redo — bonus date already set, shouldn't get bonus again
        service.do_checkin(empty_config["checkins"][0], date.today(), False)
        service.do_checkin(empty_config["checkins"][0], date.today(), True)
        # Should only get the 5 coins for redoing, no bonus
        assert empty_config["coins"] == coins_after_first

    def test_do_checkin_emits_ai_speech_on_bonus(self, service, empty_config):
        """do_checkin 全勤奖励应发射 ai_speech_needed。"""
        service.add_checkin({"name": "喝水", "enabled": True})
        speeches = []
        service.ai_speech_needed.connect(lambda action, reply: speeches.append((action, reply)))
        service.do_checkin(empty_config["checkins"][0], date.today(), True)
        # 单条打卡完成即"全部完成"，触发全勤奖励 ai_speech
        bonus_speech = [s for s in speeches if "全勤奖励" in s[0]]
        assert len(bonus_speech) == 1
        assert "数据碎片" in bonus_speech[0][1]


class TestReadMethods:
    def test_build_plan_text_empty(self, service):
        text = service.build_plan_text()
        assert "日期" in text
        assert "无" in text

    def test_build_plan_text_with_schedule(self, service, empty_config):
        service.add_schedule({
            "task": "交周报", "time": "17:00", "date": date.today().strftime("%Y-%m-%d")
        })
        text = service.build_plan_text()
        assert "交周报" in text
        assert "未完成" in text

    def test_build_plan_text_with_checkin(self, service, empty_config):
        """验证 build_plan_text 包含今日打卡信息。"""
        service.add_checkin({"name": "喝水", "enabled": True})
        text = service.build_plan_text()
        assert "喝水" in text
        assert "今日打卡" in text

    def test_get_stats_returns_correct_days(self, service):
        rows = service.get_stats(7)
        assert len(rows) == 7
        for row in rows:
            assert len(row) == 5  # (d, total, done, c_total, c_done)

    def test_categories(self, service):
        cats = service.categories()
        assert "日待办" in cats
        assert "长期" in cats

    def test_daily_rollover_resets_notified(self, service, empty_config):
        service.add_schedule({"task": "测试"})
        empty_config["schedules"][0]["notified"] = True
        service.daily_rollover()
        assert empty_config["schedules"][0]["notified"] is False
