# Calendar 模块三层解耦 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 oc.py 抽取 CalendarService 逻辑层，calendar.py 所有 dialog 不再依赖 self.pet，改为注入 service，核心业务逻辑可脱离 Qt 单测。

**Architecture:** 新增 `core/calendar_service.py` 作为数据/逻辑层。`CalendarDialog` 基类管理 service 信号生命周期（showEvent 连接、hideEvent 断开）。Dialog 只负责收集用户输入并调用 service 方法，绝不在 UI 层操作 config 字典。

**Tech Stack:** Python 3, PyQt6, pytest, Qt signals

**Source spec:** `docs/superpowers/specs/2026-07-26-calendar-decouple-design.md`

## Global Constraints

- config.json 数据格式不变
- core/utils.py 纯函数不改
- 不引入新第三方依赖
- 对话框窗口标志（WindowStaysOnTopHint 等）保持上次修复后的状态
- EditScheduleDialog/EditCheckinDialog 的 WA_DeleteOnClose 保持不变

---

## File Structure

| 文件 | 职责 |
|------|------|
| `core/calendar_service.py` **(新增)** | CalendarService(QObject) — 所有日程/打卡业务逻辑 + 信号发射 |
| `tests/test_calendar_service.py` **(新增)** | CalendarService 单测，脱离 Qt |
| `oc.py` **(修改)** | 移除 ~10 个日历方法，创建 service，连接 UI 信号 |
| `dialogs/calendar.py` **(修改)** | 新增 CalendarDialog 基类，重构 7 个 dialog |

---

### Task 1: 创建 CalendarService 核心类

**Files:**
- Create: `core/calendar_service.py`

**Interfaces:**
- Produces: `CalendarService(QObject)` with all methods listed below

`CalendarService` 从 `oc.py` 的 `DesktopPet` 中迁移业务逻辑，新增增删改原子方法封装所有 config 写操作。

- [ ] **Step 1: 创建 `core/calendar_service.py`**

```python
"""日程/打卡的业务逻辑层。所有 config 读写集中在此，UI 层绝不直接操作 config 字典。"""

from datetime import date, datetime, timedelta
from PyQt6.QtCore import QObject, pyqtSignal

from config import save_config
from core.utils import (
    new_id, sched_set_done, sched_done_on, sched_occurs_on, sched_is_recurring,
    checkin_set_done, checkin_done_on, checkin_streak,
    schedules_of_day, active_checkins,
    CATEGORIES, REPEAT_KEYS, REPEAT_LABELS, REPEAT_TEXT,
)

MILESTONES = [10, 30, 50, 100, 200, 300, 500, 800, 1000, 1500, 2000, 3000, 5000]


class CalendarService(QObject):
    """日程/打卡业务逻辑层。

    所有 config 读写操作必须通过此类的公开方法。
    Dialog 只负责收集用户输入并调用这些方法。
    可通过 Qt signals 监听变更，也可在单测中直接检查 config 字典。
    """

    # === 粗粒度信号（全局兜底） ===
    schedules_changed = pyqtSignal()
    checkins_changed = pyqtSignal()

    # === Item 级信号（精确更新） ===
    schedule_added = pyqtSignal(str)       # id
    schedule_updated = pyqtSignal(str)     # id
    schedule_removed = pyqtSignal(str)     # id
    checkin_added = pyqtSignal(str)        # id
    checkin_updated = pyqtSignal(str)      # id
    checkin_removed = pyqtSignal(str)      # id

    # === UI 反馈信号 ===
    coins_changed = pyqtSignal(int)           # new_amount
    milestone_reached = pyqtSignal(str, int)  # label, count
    bubble_needed = pyqtSignal(str)           # text → show_bubble
    ai_speech_needed = pyqtSignal(str, str)   # (user_action, ai_response)
    checkin_bonus_earned = pyqtSignal(int)    # bonus_amount

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config

    # ===================== 读方法 =====================

    def categories(self):
        return list(CATEGORIES)

    def build_plan_text(self, d=None, for_ai=True):
        """把某一天的真实日程/打卡拼成一段文字。"""
        d = d or date.today()
        items = schedules_of_day(self.config, d)
        lines = []
        for s in items:
            flag = "已完成" if sched_done_on(s, d) else "未完成"
            note = f"（备注：{s.get('note','')[:40]}）" if s.get("note") else ""
            lines.append(f"{s.get('time','--:--')} {s.get('task','')}[{flag}]{note}")
        checks = []
        if d == date.today():
            for c in active_checkins(self.config):
                checks.append(f"{c.get('name','')}[{'已打卡' if checkin_done_on(c, d) else '未打卡'}]")
        parts = [f"日期：{d.strftime('%Y年%m月%d日')}"]
        parts.append("日程：" + ("；".join(lines) if lines else "无"))
        if checks:
            parts.append("今日打卡：" + "；".join(checks))
        return "　".join(parts)

    def get_schedules_of_day(self, d=None):
        d = d or date.today()
        return schedules_of_day(self.config, d)

    def get_active_checkins(self):
        return active_checkins(self.config)

    def get_checkin_streak(self, item):
        return checkin_streak(item)

    def get_stats(self, days):
        today = date.today()
        rows = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            items = schedules_of_day(self.config, d)
            total = len(items)
            done = sum(1 for s in items if sched_done_on(s, d))
            acts = active_checkins(self.config)
            c_total = len(acts)
            c_done = sum(1 for c in acts if checkin_done_on(c, d))
            rows.append((d, total, done, c_total, c_done))
        return rows

    # ===================== 写方法 — 日程 =====================

    def add_schedule(self, data: dict) -> str:
        sid = new_id()
        data["id"] = sid
        data.setdefault("status", "pending")
        data.setdefault("notified", False)
        data.setdefault("alarm_on", True)
        data.setdefault("done_dates", [])
        data.setdefault("repeat", "once")
        data.setdefault("repeat_days", 1)
        data.setdefault("note", "")
        data.setdefault("category", data.get("category", "日待办"))
        self.config.setdefault("schedules", []).append(data)
        self._save()
        self.schedule_added.emit(sid)
        self.schedules_changed.emit()
        return sid

    def update_schedule(self, sched: dict, data: dict):
        sched.update(data)
        sched["notified"] = False  # 改过时间后今天可重新提醒
        self._save()
        self.schedule_updated.emit(sched.get("id", ""))
        self.schedules_changed.emit()

    def delete_schedule(self, sched_id: str):
        lst = self.config.get("schedules", [])
        for i, s in enumerate(lst):
            if s.get("id") == sched_id:
                del lst[i]
                break
        self._save()
        self.schedule_removed.emit(sched_id)
        self.schedules_changed.emit()

    def mark_schedule_done(self, sched: dict, d=None, done=True) -> bool:
        d = d or date.today()
        if not sched_set_done(sched, d, done):
            return False
        st = self.config.setdefault("stats", {})
        if done:
            st["todo_done_total"] = st.get("todo_done_total", 0) + 1
            self.config["coins"] = self.config.get("coins", 0) + 20
            self._save()
            self.coins_changed.emit(self.config["coins"])
            self.ai_speech_needed.emit(
                f"系统：用户完成了待办事项 [{sched.get('task','')}]",
                f"【normal】计划执行得不错。 [{sched.get('task','')}] 已经从待办里划掉了。"
                f"这是给你的20数据碎片。")
        else:
            st["todo_done_total"] = max(0, st.get("todo_done_total", 0) - 1)
            self.config["coins"] = max(0, self.config.get("coins", 0) - 20)
            self._save()
            self.coins_changed.emit(self.config["coins"])
        self.schedule_updated.emit(sched.get("id", ""))
        self.schedules_changed.emit()
        self._check_milestones()
        return True

    # ===================== 写方法 — 打卡 =====================

    def add_checkin(self, data: dict) -> str:
        cid = new_id()
        data["id"] = cid
        data.setdefault("created", date.today().strftime("%Y-%m-%d"))
        data.setdefault("done_dates", [])
        data.setdefault("archived", False)
        data.setdefault("enabled", True)
        self.config.setdefault("checkins", []).append(data)
        self._save()
        self.checkin_added.emit(cid)
        self.checkins_changed.emit()
        return cid

    def update_checkin(self, item: dict, data: dict):
        item.update(data)
        self._save()
        self.checkin_updated.emit(item.get("id", ""))
        self.checkins_changed.emit()

    def delete_checkin(self, item_id: str):
        lst = self.config.get("checkins", [])
        for i, c in enumerate(lst):
            if c.get("id") == item_id:
                del lst[i]
                break
        self._save()
        self.checkin_removed.emit(item_id)
        self.checkins_changed.emit()

    def do_checkin(self, item: dict, d=None, done=True, quiet=False) -> bool:
        d = d or date.today()
        if not checkin_set_done(item, d, done):
            return False
        st = self.config.setdefault("stats", {})
        if done:
            st["checkin_done_total"] = st.get("checkin_done_total", 0) + 1
            self.config["coins"] = self.config.get("coins", 0) + 5
        else:
            st["checkin_done_total"] = max(0, st.get("checkin_done_total", 0) - 1)
            self.config["coins"] = max(0, self.config.get("coins", 0) - 5)
        self._save()
        self.coins_changed.emit(self.config["coins"])
        self.checkin_updated.emit(item.get("id", ""))
        self.checkins_changed.emit()

        if done and d == date.today() and not quiet:
            self._check_checkin_bonus()
        if not quiet:
            self._check_milestones()
        return True

    def daily_rollover(self):
        for s in self.config.get("schedules", []):
            if isinstance(s, dict) and s.get("notified"):
                s["notified"] = False
        self._save()
        self.schedules_changed.emit()
        self.checkins_changed.emit()

    # ===================== 内部方法 =====================

    def _save(self):
        save_config(self.config)

    def _check_milestones(self):
        st = self.config.setdefault("stats", {})
        for key, reached_key, label in (
                ("todo_done_total", "milestone_todo", "待办"),
                ("checkin_done_total", "milestone_checkin", "打卡")):
            total = st.get(key, 0)
            reached = st.get(reached_key, 0)
            new_mark = None
            for m in MILESTONES:
                if total >= m > reached:
                    new_mark = m
            if new_mark is None:
                continue
            st[reached_key] = new_mark
            reward = int(50 + (new_mark * 0.5))
            self.config["coins"] = self.config.get("coins", 0) + reward
            self._save()
            self.coins_changed.emit(self.config["coins"])
            self.milestone_reached.emit(label, new_mark)
            self.ai_speech_needed.emit(
                f"系统：用户累计完成{label}达到{new_mark}次，获得{reward}数据碎片里程碑奖励",
                f"【dark】统计模块提示：你累计完成的{label}已经到了 "
                f"<font color='#4169E1'>{new_mark}</font> 次。"
                f"坚持这种事本身就比结果稀有。奖励 <font color='#FFD700'>{reward} 数据碎片</font>。")

    def _check_checkin_bonus(self):
        today = date.today()
        acts = [c for c in active_checkins(self.config) if c.get("enabled", True)]
        if not acts:
            return
        if not all(checkin_done_on(c, today) for c in acts):
            return
        if self.config.get("checkin_last_bonus_date") == today.strftime("%Y-%m-%d"):
            return
        import random
        bonus = random.randint(30, 60)
        self.config["checkin_last_bonus_date"] = today.strftime("%Y-%m-%d")
        self.config["coins"] = self.config.get("coins", 0) + bonus
        self._save()
        self.coins_changed.emit(self.config["coins"])
        self.checkin_bonus_earned.emit(bonus)
        self.ai_speech_needed.emit(
            f"系统：用户今日打卡全部完成，获得{bonus}数据碎片全勤奖励",
            f"【shy】……今天的{len(acts)}项打卡一个没落。哼，算你有点自律。"
            f"额外奖励 <font color='#FFD700'>{bonus} 数据碎片</font>，拿好。")
```

- [ ] **Step 2: 验证文件语法**

```bash
python -m py_compile core/calendar_service.py && echo "OK"
```

- [ ] **Step 3: 提交**

```bash
git add core/calendar_service.py
git commit -m "feat: 新增 CalendarService 业务逻辑层

从 oc.py DesktopPet 迁移日程/打卡业务方法，新增原子增删改封装。
所有 config 写操作集中在此类，通过 Qt signals 通知 UI 变更。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 编写 CalendarService 单元测试

**Files:**
- Create: `tests/test_calendar_service.py`

**Interfaces:**
- Consumes: `CalendarService(config)` from Task 1
- Produces: pytest 测试套件

- [ ] **Step 1: 创建测试目录和文件**

```bash
mkdir -p tests
```

```python
"""CalendarService 业务逻辑单测。不需要 Qt GUI。"""

import pytest
from datetime import date, timedelta
from core.calendar_service import CalendarService, MILESTONES


@pytest.fixture
def empty_config():
    return {"schedules": [], "checkins": [], "coins": 0, "stats": {}}


@pytest.fixture
def service(empty_config):
    return CalendarService(empty_config)


class TestScheduleWrite:
    def test_add_schedule_returns_id_and_appends(self, service, empty_config):
        sid = service.add_schedule({
            "task": "测试待办", "time": "09:00", "category": "日待办"
        })
        assert isinstance(sid, str)
        assert len(sid) > 0
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
        assert ("added", sid) in signals
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
        assert updated_id == [sid]

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
        assert removed == [sid]

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

    def test_milestone_at_100_todo(self, service, empty_config):
        empty_config["stats"]["todo_done_total"] = 99
        empty_config["stats"]["milestone_todo"] = 50
        service.add_schedule({"task": "第100个"})
        service.mark_schedule_done(empty_config["schedules"][0], date.today(), True)
        assert empty_config["coins"] > 20  # 20 + milestone bonus
        assert empty_config["stats"]["milestone_todo"] == 100

    def test_milestone_not_triggered_when_below_threshold(self, service, empty_config):
        empty_config["stats"]["todo_done_total"] = 5
        empty_config["stats"]["milestone_todo"] = 0
        service.add_schedule({"task": "第6个"})
        service.mark_schedule_done(empty_config["schedules"][0], date.today(), True)
        assert empty_config["stats"].get("milestone_todo", 0) == 0  # 不到10不触发


class TestCheckinWrite:
    def test_add_checkin(self, service, empty_config):
        cid = service.add_checkin({"name": "喝水", "remind_times": ["09:00"]})
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
        service.do_checkin(c, date.today(), True)
        assert empty_config["coins"] == 5
        assert empty_config["stats"]["checkin_done_total"] == 1

    def test_do_checkin_undo(self, service, empty_config):
        service.add_checkin({"name": "喝水", "enabled": True})
        c = empty_config["checkins"][0]
        service.do_checkin(c, date.today(), True)
        service.do_checkin(c, date.today(), False)
        assert empty_config["coins"] == 0

    def test_do_checkin_idempotent(self, service, empty_config):
        service.add_checkin({"name": "喝水", "enabled": True})
        c = empty_config["checkins"][0]
        assert service.do_checkin(c, date.today(), True) is True
        assert service.do_checkin(c, date.today(), True) is False

    def test_all_done_bonus_once_per_day(self, service, empty_config):
        service.add_checkin({"name": "A", "enabled": True})
        service.add_checkin({"name": "B", "enabled": True})
        coins_before = empty_config["coins"]
        service.do_checkin(empty_config["checkins"][0], date.today(), True)
        service.do_checkin(empty_config["checkins"][1], date.today(), True)
        # 应包含 5+5 (打卡) + bonus (30-60)
        assert empty_config["coins"] >= coins_before + 40

    def test_all_done_bonus_not_double_counted(self, service, empty_config):
        service.add_checkin({"name": "A", "enabled": True})
        service.do_checkin(empty_config["checkins"][0], date.today(), True)
        coins_after_first = empty_config["coins"]
        # Undo and redo — bonus date already set, shouldn't get bonus again
        service.do_checkin(empty_config["checkins"][0], date.today(), False)
        service.do_checkin(empty_config["checkins"][0], date.today(), True)
        # Should only get the 5 coins for redoing, no bonus
        assert empty_config["coins"] == coins_after_first


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

    def test_get_stats_returns_correct_days(self, service):
        rows = service.get_stats(7)
        assert len(rows) == 7

    def test_categories(self, service):
        cats = service.categories()
        assert "日待办" in cats
        assert "长期" in cats

    def test_daily_rollover_resets_notified(self, service, empty_config):
        service.add_schedule({"task": "测试"})
        empty_config["schedules"][0]["notified"] = True
        service.daily_rollover()
        assert empty_config["schedules"][0]["notified"] is False
```

- [ ] **Step 2: 运行测试确认通过**

```bash
python -m pytest tests/test_calendar_service.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_calendar_service.py
git commit -m "test: CalendarService 业务逻辑单测

覆盖日程/打卡的增删改、状态切换、金币奖励、里程碑触发、
全勤奖励、幂等性、daily rollover。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 修改 oc.py — 创建 CalendarService 并连接信号

**Files:**
- Modify: `oc.py`

**Interfaces:**
- Consumes: `CalendarService` from Task 1
- Produces: `DesktopPet.calendar_service` 属性，供 open_dialog 注入

**要点：** 从 DesktopPet 中移除已迁移到 CalendarService 的方法，但保留 `speak_today_plan`（它依赖 send_msg/AI），改为内部调用 `self.calendar_service.build_plan_text(d)`。

- [ ] **Step 1: 在 oc.py 顶部添加 import**

在现有 `from core.utils import *` 之后添加一行：
```python
from core.calendar_service import CalendarService
```

- [ ] **Step 2: 在 DesktopPet.__init__ 中创建 service 并连接信号**

在 `self.init_timers()` 之前，添加：
```python
# ===== CalendarService: 日程/打卡业务逻辑层 =====
self.calendar_service = CalendarService(self.config)

# 连接 UI 反馈信号
self.calendar_service.bubble_needed.connect(self.show_bubble)
self.calendar_service.ai_speech_needed.connect(self.inject_system_event)
self.calendar_service.coins_changed.connect(self._on_calendar_coins_changed)
self.calendar_service.milestone_reached.connect(self._on_calendar_milestone)
```

添加两个简单的 slot 方法：
```python
def _on_calendar_coins_changed(self, amount):
    """CalendarService 通知金币变更，更新已打开的商城面板"""
    dlg = getattr(self, "dlg_StoreDialog", None)
    if dlg is not None and dlg.isVisible():
        try:
            dlg.coin_label.setText(
                f"<h2>💰 当前资产：{amount} 数据碎片</h2>")
        except RuntimeError:
            self.dlg_StoreDialog = None

def _on_calendar_milestone(self, label, count):
    """CalendarService 通知里程碑达成，改变心情"""
    self.change_mood(8)
```

- [ ] **Step 3: 修改 speak_today_plan 委托给 service**

将 `speak_today_plan` 方法改为：
```python
def speak_today_plan(self, d=None):
    d = d or date.today()
    data = self.calendar_service.build_plan_text(d)
    items = self.calendar_service.get_schedules_of_day(d)
    if not items and not (d == date.today() and self.calendar_service.get_active_checkins()):
        self.inject_system_event(
            f"系统：用户查看了 {d.strftime('%m月%d日')} 的安排，当天没有任何日程",
            f"【normal】{d.strftime('%m月%d日')}。你什么都没安排。是打算放空，还是单纯忘了记？")
        return
    self.send_msg(
        f"【系统后台强制指令：以下是用户的真实日程数据，请严格按照这些内容播报，"
        f"绝对不许添加、删减或编造任何条目。用你的口吻简短复述并给一句评价（60字以内）。\n{data}】",
        hidden=True)
```

- [ ] **Step 4: 修改 core_clock_tick 中的调用**

- `self.check_milestones()` → `self.calendar_service._check_milestones()`
  实际上这已经在 service 的 `mark_schedule_done` 和 `do_checkin` 内部自动调用了。但 `core_clock_tick` 已经不再主动调 `check_milestones` ——检查一下，如果当前没有主动调，就无需改。

- `self.daily_rollover()` → `self.calendar_service.daily_rollover()`

查找 `def core_clock_tick` 中 `daily_rollover` 的调用行，改为：
```python
self.calendar_service.daily_rollover()
```

- [ ] **Step 5: 修改 queue_reminder 中 checkin 提醒的数据获取**

将 `active_checkins(self.config)` 改为 `self.calendar_service.get_active_checkins()`

- [ ] **Step 6: 修改 open_dialog 方法**

在 `open_dialog` 中，对于 calendar 类 dialog，传入 service：

```python
def open_dialog(self, DialogClass, *args):
    suffix = "_" + str(args[0]) if args and isinstance(args[0], str) else ""
    dlg_name = f"dlg_{DialogClass.__name__}{suffix}"
    
    # 判断是否需要注入 CalendarService
    _CALENDAR_DIALOGS = (
        "ScheduleDialog", "MiniCalendarDialog", "CheckinDialog",
        "StatsDialog", "DayDetailDialog", "EditScheduleDialog",
        "EditCheckinDialog")
    needs_service = DialogClass.__name__ in _CALENDAR_DIALOGS
    
    if not hasattr(self, dlg_name) or getattr(self, dlg_name) is None:
        if needs_service:
            new_dlg = DialogClass(self.calendar_service, self, *args)
        else:
            new_dlg = DialogClass(self, *args)
        setattr(self, dlg_name, new_dlg)
        new_dlg.show()
    else:
        dlg = getattr(self, dlg_name)
        try:
            if not dlg.isVisible():
                if hasattr(dlg, "refresh_list"):
                    dlg.refresh_list()
                dlg.show()
            dlg.activateWindow()
            dlg.raise_()
        except RuntimeError:
            if needs_service:
                new_dlg = DialogClass(self.calendar_service, self, *args)
            else:
                new_dlg = DialogClass(self, *args)
            setattr(self, dlg_name, new_dlg)
            new_dlg.show()
```

- [ ] **Step 7: 移除已迁移的方法**

删除 DesktopPet 中的以下方法（保留方法体为空或直接删除）：
- `mark_schedule_done`（整个方法删除，~20 行）
- `do_checkin`（整个方法删除，~20 行）
- `check_checkin_bonus`（整个方法删除，~20 行）
- `check_milestones`（整个方法删除，~25 行）
- `build_plan_text`（整个方法删除，~25 行）
- `daily_rollover`（整个方法删除，~15 行）
- `MILESTONES` 类属性（删除）

- [ ] **Step 8: 修改 refresh_dialogs 中的日历相关刷新**

`refresh_dialogs` 保留在 pet（它是窗口管理），但调用的 dialog 前缀可能需要调整。当前不需要改——dialog 通过 service 信号自动刷新。

- [ ] **Step 9: 验证 — oc.py 语法和导入**

```bash
python -m py_compile oc.py && echo "OK"
```

- [ ] **Step 10: 提交**

```bash
git add oc.py
git commit -m "refactor: oc.py 接入 CalendarService

- 创建 CalendarService 实例并连接 UI 反馈信号
- speak_today_plan 委托 service.build_plan_text
- daily_rollover 委托 service.daily_rollover
- open_dialog 对 calendar dialog 自动注入 service
- 移除已迁移的 7 个业务方法和 MILESTONES 常量

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 在 calendar.py 添加 CalendarDialog 基类

**Files:**
- Modify: `dialogs/calendar.py`

**Interfaces:**
- Produces: `CalendarDialog(QDialog)` 基类，包含信号生命周期管理
- Consumes: `CalendarService` from Task 1

- [ ] **Step 1: 在 calendar.py 顶部（import 之后，第一个 class 之前）添加基类**

```python
class CalendarDialog(QDialog):
    """日程/打卡 Dialog 基类。

    统一管理 CalendarService 信号的生命周期：
    - showEvent 连接信号 → 自动刷新
    - hideEvent 断开信号 → WA_DeleteOnClose 窗口安全销毁
    - closeEvent 强制断开 → 双重保险
    """

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._connected = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._connected:
            self._connect_service_signals()
            self._connected = True
        if hasattr(self, 'refresh_list'):
            self.refresh_list()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._disconnect_service_signals()
        self._connected = False

    def closeEvent(self, event):
        self._disconnect_service_signals()
        self._connected = False
        super().closeEvent(event)

    def _connect_service_signals(self):
        try:
            self.service.schedules_changed.connect(self._on_schedules_changed)
        except TypeError:
            pass
        try:
            self.service.checkins_changed.connect(self._on_checkins_changed)
        except TypeError:
            pass

    def _disconnect_service_signals(self):
        try:
            self.service.schedules_changed.disconnect(self._on_schedules_changed)
        except TypeError:
            pass
        try:
            self.service.checkins_changed.disconnect(self._on_checkins_changed)
        except TypeError:
            pass

    @property
    def pet(self):
        """获取 DesktopPet 引用。仅用于需要 AI 语音等 pet 能力的场景。
        向上遍历 parent 链查找 DesktopPet 实例。"""
        p = self.parent()
        while p is not None:
            if hasattr(p, 'speak_today_plan'):
                return p
            p = p.parent()
        return None

    def _on_schedules_changed(self):
        if self.isVisible() and hasattr(self, 'refresh_list'):
            self.refresh_list()

    def _on_checkins_changed(self):
        if self.isVisible() and hasattr(self, 'refresh_list'):
            self.refresh_list()
```

- [ ] **Step 2: 验证语法**

```bash
python -m py_compile dialogs/calendar.py && echo "OK"
```

- [ ] **Step 3: 提交**

```bash
git add dialogs/calendar.py
git commit -m "feat: 新增 CalendarDialog 基类

统一管理 service 信号的连接/断开生命周期。
showEvent 连接、hideEvent 断开 —— 防止 WA_DeleteOnClose
窗口 C++ 层销毁后仍收到信号导致 RuntimeError。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 重构 ScheduleDialog、MiniCalendarDialog、CheckinDialog、StatsDialog

**Files:**
- Modify: `dialogs/calendar.py`

**Interfaces:**
- Consumes: `CalendarDialog` from Task 4, `CalendarService` from Task 1

这四个 dialog 都是 "列表展示型"——打开后展示数据，自动刷新。改造模式相同：继承 CalendarDialog，`parent_pet` → `service, parent`，`self.pet` → `self.service`。

- [ ] **Step 1: ScheduleDialog**

改构造签名：
```python
class ScheduleDialog(CalendarDialog):
    def __init__(self, service, parent=None):
        super().__init__(service, parent)
```
所有 `self.pet` 替换为 `self.service`：
- `self.pet.config` → `self.service.config`
- `self.pet.mark_schedule_done(...)` → `self.service.mark_schedule_done(...)`
- `self.pet.open_dialog(MiniCalendarDialog)` → 保留。MiniCalendarDialog 现在需要 service，改为 `MiniCalendarDialog(self.service, self)`
- `self.pet.speak_today_plan()` → 保留（pet 方法），但需通过 parent 链获取 pet。简单方案：`parent().calendar_service` 不行...实际上 `parent` 是 DesktopPet。可以加一个 `_pet()` 辅助方法，或者在 ScheduleDialog 上存 `self._pet = parent`。

**关键决策**：`speak_today_plan` 需要 AI 能力（send_msg），只有 DesktopPet 能做。`CalendarDialog.pet` 属性（Task 4 已定义）通过遍历 parent 链获取 DesktopPet 引用。

在 ScheduleDialog 中：
- `self.pet.open_dialog(MiniCalendarDialog)` → `MiniCalendarDialog(self.service, self.pet).show()`
  或者直接不调 open_dialog，手动 show。
- `save_config(self.pet.config)` → 删除，service 内部已 save
- `self.pet.refresh_dialogs(...)` → 删除，信号自动处理

ScheduleDialog 中 cal_btn 打开日历：
```python
self.cal_btn.clicked.connect(
    lambda: MiniCalendarDialog(self.service, self.pet).show())
```

ScheduleDialog 中 mark_done：
```python
def mark_done(self, sched, done=True):
    self.service.mark_schedule_done(sched, date.today(), done)
    # refresh_list 由 service.schedules_changed 信号自动触发
```

ScheduleDialog 中 del_task：用 `self.service.delete_schedule(sid)` 替换直接操作列表+save。

ScheduleDialog 中 add_schedule：用 `self.service.add_schedule(data)` 替换 `self.pet.config.setdefault(...).append(...)`。

ScheduleDialog 中 add_detailed：
```python
def add_detailed(self):
    dlg = EditScheduleDialog(
        self.service, self,
        default_category=self.cat_combo.currentText())
    dlg.show()
```

- [ ] **Step 2: MiniCalendarDialog**

```python
class MiniCalendarDialog(CalendarDialog):
    def __init__(self, service, parent=None):
        super().__init__(service, parent)
```

替换：
- `self.pet.config` → `self.service.config`
- `self.pet.mark_schedule_done(...)` → `self.service.mark_schedule_done(...)`
- `self.pet.do_checkin(...)` → `self.service.do_checkin(...)`
- `self.pet.speak_today_plan(d)` → `self.pet.speak_today_plan(d)` (pet 属性)
- `self.pet.open_dialog(CheckinDialog)` → `CheckinDialog(self.service, self.pet).show()`
- `self.pet.open_dialog(StatsDialog)` → `StatsDialog(self.service, self.pet).show()`
- `EditScheduleDialog(self, ...).exec()` → `EditScheduleDialog(self.service, self, ...).show()`

- [ ] **Step 3: CheckinDialog**

```python
class CheckinDialog(CalendarDialog):
    def __init__(self, service, parent=None):
        super().__init__(service, parent)
```

替换：
- `self.pet.config` → `self.service.config`
- `self.pet.do_checkin(...)` → `self.service.do_checkin(...)`
- `self.pet.open_dialog(StatsDialog)` → `StatsDialog(self.service, self.pet).show()`
- `EditCheckinDialog(self).exec()` → `EditCheckinDialog(self.service, self).show()`
- `save_config(self.pet.config)` → 删除
- archive/delete 操作改成调 service：
  - `item["archived"] = not item.get("archived")` → `self.service.update_checkin(item, {"archived": not item.get("archived", False)})`
  - 直接删除列表元素 → `self.service.delete_checkin(cid)`

- [ ] **Step 4: StatsDialog**

```python
class StatsDialog(CalendarDialog):
    def __init__(self, service, parent=None):
        super().__init__(service, parent)
```

替换：
- `self.pet.config` → `self.service.config`
- `self._collect(days)` → `self.service.get_stats(days)`
- `active_checkins(self.pet.config)` → `self.service.get_active_checkins()`
- `checkin_streak(c, today)` → `self.service.get_checkin_streak(c)`
- `schedules_of_day(self.pet.config, d)` → `self.service.get_schedules_of_day(d)`
- `sched_done_on(s, d)` → `sched_done_on` from core.utils (纯函数，保持)

- [ ] **Step 5: 验证语法**

```bash
python -m py_compile dialogs/calendar.py && echo "OK"
```

- [ ] **Step 6: 提交**

```bash
git add dialogs/calendar.py
git commit -m "refactor: ScheduleDialog/MiniCalendarDialog/CheckinDialog/StatsDialog 接入 CalendarService

四个「列表展示型」dialog 改为继承 CalendarDialog，构造签名改为 (service, parent)。
self.pet → self.service，config 直接操作 → service 原子方法。
speak_today_plan/open_dialog 通过 CalendarDialog.pet 属性回退获取 DesktopPet。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 重构 DayDetailDialog、EditScheduleDialog、EditCheckinDialog

**Files:**
- Modify: `dialogs/calendar.py`

**Interfaces:**
- Consumes: `CalendarDialog` from Task 4, `CalendarService` from Task 1

DayDetailDialog 继承 CalendarDialog（需要自动刷新）。EditScheduleDialog 和 EditCheckinDialog **不**继承 CalendarDialog——它们是编辑弹窗，不需要连接全局信号。

- [ ] **Step 1: DayDetailDialog**

```python
class DayDetailDialog(CalendarDialog):
    def __init__(self, service, parent, the_date):
        super().__init__(service, parent)
        # ...
```

替换：
- `self.pet = parent.pet if hasattr(parent, "pet") else parent` → 删除这行，使用 `self.pet` 属性
- `self.pet.config` → `self.service.config`
- `self.pet.mark_schedule_done(...)` → `self.service.mark_schedule_done(...)`
- `self.pet.do_checkin(...)` → `self.service.do_checkin(...)`
- `self.pet.speak_today_plan(self.the_date)` → `self.pet.speak_today_plan(self.the_date)`
- `EditScheduleDialog(self, sched=sched).show()` → `EditScheduleDialog(self.service, self, sched=sched).show()`
- `EditScheduleDialog(self, default_date=self.the_date).show()` → `EditScheduleDialog(self.service, self, default_date=self.the_date).show()`

- [ ] **Step 2: EditScheduleDialog**

```python
class EditScheduleDialog(QDialog):  # 不继承 CalendarDialog
    def __init__(self, service, parent, sched=None, default_date=None, default_category=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.service = service
        self.sched = sched
        self.is_new = sched is None
        # ...
```

保存逻辑从直接操作 config 字典改为：
```python
def save(self):
    task = self.title_input.text().strip()
    if not task:
        QMessageBox.warning(self, "提示", "标题不能为空。")
        return
    d = self.date_edit.date()
    data = {
        "task": task,
        "category": self.cat_combo.currentText(),
        "time": self.time_edit.time().toString("HH:mm"),
        "date": f"{d.year():04d}-{d.month():02d}-{d.day():02d}" if self.date_check.isChecked() else "",
        "repeat": REPEAT_KEYS[self.repeat_combo.currentIndex()] if self.date_check.isChecked() else "once",
        "repeat_days": self.repeat_days.value(),
        "note": self.note_edit.toPlainText().strip(),
    }
    if self.is_new:
        self.service.add_schedule(data)
    else:
        self.service.update_schedule(self.sched, data)
    self.accept()
    # 不再需要 QTimer.singleShot + save_config + refresh_dialogs
    # Service 内部已 save + emit signals
```

不再需要 `self.pet` 引用。

- [ ] **Step 3: EditCheckinDialog**

```python
class EditCheckinDialog(QDialog):  # 不继承 CalendarDialog
    def __init__(self, service, parent, item=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.service = service
        self.item = item
        self.is_new = item is None
        # ...
```

保存逻辑：
```python
def save(self):
    name = self.name_input.text().strip()
    if not name:
        QMessageBox.warning(self, "提示", "名称不能为空。")
        return
    times = [...]  # 解析逻辑不变
    data = {"name": name, "note": self.note_edit.toPlainText().strip(),
            "remind_times": times, "enabled": self.enable_check.isChecked()}
    if self.is_new:
        self.service.add_checkin(data)
    else:
        self.service.update_checkin(self.item, data)
    self.accept()
```

- [ ] **Step 4: EditScheduleDialog 的调用方更新**

所有打开 EditScheduleDialog 的地方更新构造调用：
- `ScheduleDialog.add_detailed`: `EditScheduleDialog(self.service, self, default_category=...)`
- `DayDetailDialog.edit`: `EditScheduleDialog(self.service, self, sched=sched)`
- `DayDetailDialog.add_here`: `EditScheduleDialog(self.service, self, default_date=...)`
- `MiniCalendarDialog.add_on_selected`: `EditScheduleDialog(self.service, self, default_date=...)`

EditCheckinDialog：
- `CheckinDialog.add_item`: `EditCheckinDialog(self.service, self)`
- `CheckinDialog.edit`: `EditCheckinDialog(self.service, self, item=item)`

- [ ] **Step 5: 验证语法和导入**

```bash
python -m py_compile dialogs/calendar.py && echo "OK"
python -c "from dialogs.calendar import *; print('all imports OK')"
```

- [ ] **Step 6: 提交**

```bash
git add dialogs/calendar.py
git commit -m "refactor: DayDetailDialog/EditScheduleDialog/EditCheckinDialog 接入 CalendarService

DayDetailDialog 继承 CalendarDialog，自动刷新。
EditScheduleDialog/EditCheckinDialog 不继承基类，save() 改为调 service 原子方法。
所有 config 直接操作从 UI 层移除。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 集成验证与清理

**Files:**
- 运行: `tests/test_calendar_service.py`, `oc.py`, `dialogs/calendar.py`

- [ ] **Step 1: 跑单测**

```bash
python -m pytest tests/test_calendar_service.py -v
```
预期：全部 PASS

- [ ] **Step 2: 验证全文件语法**

```bash
python -m py_compile oc.py && echo "oc.py OK"
python -m py_compile dialogs/calendar.py && echo "calendar.py OK"
python -m py_compile core/calendar_service.py && echo "calendar_service.py OK"
```

- [ ] **Step 3: 验证 calendar.py 中 self.pet 残留**

```bash
grep -c "self\.pet" dialogs/calendar.py
```
预期输出：0（或仅剩 DayDetailDialog 中通过 `self.pet.speak_today_plan()` 调用的少量引用，通过 CalendarDialog.pet 属性获取）

- [ ] **Step 4: 验证 calendar.py 中无直接 config 写操作**

```bash
grep -n "\.config\[" dialogs/calendar.py
grep -n "save_config" dialogs/calendar.py
```
预期：无输出（所有写操作已迁移到 service）

- [ ] **Step 5: 提交最终检查**

```bash
git diff --stat
git add -A
git commit -m "chore: Calendar 三层解耦完成，清理残留引用

所有单测通过，所有语法检查通过。
calendar.py 中 self.pet 直接引用已清零，config 写操作已全部迁移至 CalendarService。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Verification

完成所有 task 后：

1. `python -m pytest tests/test_calendar_service.py -v` — 全部 PASS
2. 在 Windows 上手動验证：
   - 右键 → 日程系统 → 添加/编辑/删除/标记完成 → 正常
   - 右键 → 迷你月历 → 加日程/打卡 → 正常
   - 右键 → 每日打卡 → 新建/编辑/打卡 → 正常
   - 同时打开多个日历面板 → 一个操作后所有面板自动刷新
   - EditScheduleDialog 保存后关闭 → 不闪退
