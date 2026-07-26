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
