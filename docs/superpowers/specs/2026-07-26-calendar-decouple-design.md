# Calendar 模块三层解耦 — 设计文档

日期：2026-07-26　修订：v2（技术评审后）

## 问题

`oc.py`（1440 行）和 `dialogs/calendar.py`（1221 行）紧密耦合。所有 calendar dialog 通过 `self.pet` 直接访问 `DesktopPet`——读 config、调业务方法、保存配置、发气泡消息、刷新其他窗口。导致：

1. **无法单测**：任何 dialog 的实例化都需要完整 DesktopPet 环境
2. **不可维护**：改一个业务规则需要同时改 oc.py 和所有调用方
3. **职责混乱**：业务逻辑（金币计算、里程碑、打卡判定）散落在 oc.py 和 dialog 里

## 目标

- 从 oc.py 抽取 `CalendarService`，作为纯数据/逻辑层
- Calendar dialog 不再持有 `self.pet`，改为接收 service
- Service 通过 Qt signals 向外通知 UI 反馈（气泡、AI 语音）
- 核心业务逻辑可脱离 Qt 单测

## 架构

```
oc.py (DesktopPet)
  ├─ 创建 CalendarService 实例
  ├─ 连接 service 信号 → show_bubble / inject_system_event
  └─ open_dialog 时注入 service

dialogs/calendar.py (视图层)
  ├─ 各 Dialog: 纯 Qt UI，继承 CalendarDialog 基类
  ├─ Dialog 只负责：收集用户输入 → 调用 service 方法 → 展示数据
  ├─ 绝不在 UI 层直接操作 config 字典
  └─ 连接 service.item 级信号 → 局部刷新列表

core/calendar_service.py (逻辑层) ★新增★
  ├─ CalendarService(QObject)
  ├─ 持有 config 引用，封装所有读写操作
  ├─ 原子增删改方法：add_schedule, update_schedule, delete_schedule 等
  └─ 发射粗粒度 + item 级信号通知变更

core/utils.py (数据层) 已有，不改
  └─ schedules_of_day, sched_done_on 等纯函数
```

## CalendarService 设计

### 构造

```python
class CalendarService(QObject):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
```

`config` 是 mutable dict，DesktopPet 持有同一份引用。Service 直接修改 config。**外部（Dialog）绝不直接操作 config 字典。**

### 公开方法 — 读路径 (Read)

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `build_plan_text(d)` | date | str | 当天日程+打卡摘要 |
| `schedules_of_day(d)` | date | list[dict] | 委托 core.utils.schedules_of_day |
| `active_checkins()` | — | list[dict] | 委托 core.utils.active_checkins |
| `checkin_streak(item)` | dict | int | 委托 core.utils.checkin_streak |
| `get_stats(days)` | int | dict | 近 N 天的统计数据 |
| `categories()` | — | list[str] | 分类列表常量 |

### 公开方法 — 写路径 (Write)

| 方法 | 参数 | 返回值 | 副作用 |
|------|------|--------|--------|
| `add_schedule(data)` | dict (task/time/date/repeat…) | str (new id) | emit schedule_added, schedules_changed, save |
| `update_schedule(sched, data)` | dict (原对象), dict (新字段) | — | emit schedule_updated, schedules_changed, save |
| `delete_schedule(sched_id)` | str | — | emit schedule_removed, schedules_changed, save |
| `mark_schedule_done(sched, d, done)` | dict, date, bool | bool | 金币、里程碑、emit signals、save |
| `add_checkin(data)` | dict (name/note/times…) | str | emit checkin_added, checkins_changed, save |
| `update_checkin(item, data)` | dict, dict | — | emit checkin_updated, checkins_changed, save |
| `delete_checkin(item_id)` | str | — | emit checkin_removed, checkins_changed, save |
| `do_checkin(item, d, done, quiet)` | dict, date, bool, bool | bool | 金币、全勤、里程碑、emit signals、save |
| `daily_rollover()` | — | — | 跨天清理 notified 标记、save、emit |

**关键原则：Dialog 只负责收集用户输入并传给 Service，绝不在 UI 层直接 update() 原始数据字典。**

#### 写路径示例：add_schedule

```
1. 生成 id (new_id())
2. 补充默认字段 (status="pending", done_dates=[] 等)
3. config["schedules"].append(data)
4. save()
5. emit schedule_added(id)
6. emit schedules_changed
```

#### 写路径示例：update_schedule

```
1. sched.update(data)           ← 唯一操作字典的地方，在 Service 内部
2. sched["notified"] = False    ← 改了时间后允许今天重新提醒
3. save()
4. emit schedule_updated(sched["id"])
5. emit schedules_changed
```

### 信号 — 双层粒度

```python
# === 粗粒度（全局兜底，简单场景用） ===
schedules_changed = pyqtSignal()   # 任何日程变更
checkins_changed = pyqtSignal()    # 任何打卡变更

# === Item 级（精确更新，避免全量重建） ===
schedule_added = pyqtSignal(str)       # id
schedule_updated = pyqtSignal(str)     # id
schedule_removed = pyqtSignal(str)     # id
checkin_added = pyqtSignal(str)        # id
checkin_updated = pyqtSignal(str)      # id
checkin_removed = pyqtSignal(str)      # id

# === UI 反馈信号 ===
coins_changed = pyqtSignal(int)          # new_amount
milestone_reached = pyqtSignal(str, int) # label, count
bubble_needed = pyqtSignal(str)          # 格式化文本 → show_bubble
ai_speech_needed = pyqtSignal(str, str)  # (user_action, ai_response)
checkin_bonus_earned = pyqtSignal(int)   # bonus_amount
```

**信号策略：** MVP 阶段 Dialog 可以连 `schedules_changed` 做全量 `refresh_list()`——当前数据量下全量重建几十条日程的 QWidget 开销可忽略。后续若数据量增长，改为连 `schedule_updated(id)` 等 item 级信号做局部更新（只查找对应 ID 的 QListWidgetItem 并更新其 widget 状态）。

### 关键方法逻辑

#### mark_schedule_done

```
1. 调 core.utils.sched_set_done(sched, d, done) → 纯数据操作
2. 根据 done/undo 更新 stats.todo_done_total 和 coins
3. save()
4. emit schedule_updated(id) + schedules_changed + coins_changed
5. emit bubble_needed / ai_speech_needed (如果有气泡文本)
6. 调 _check_milestones()
```

#### do_checkin

```
1. 调 core.utils.checkin_set_done(item, d, done)
2. 更新 stats.checkin_done_total 和 coins
3. 检查全勤奖励 (_check_checkin_bonus)
4. save()
5. emit checkin_updated(id) + checkins_changed + coins_changed
6. _check_milestones()
```

## dialogs/calendar.py 变更

### CalendarDialog 基类 —— 管理信号生命周期

```python
class CalendarDialog(QDialog):
    """所有 calendar dialog 的基类。
    统一管理 service 引用、信号连接/断开、自动刷新。
    """

    def __init__(self, service: CalendarService, parent=None):
        super().__init__(parent)
        self.service = service
        self._connected = False

    def showEvent(self, event):
        """窗口显示时连接信号，隐藏时断开，避免已销毁对象收到信号"""
        super().showEvent(event)
        if not self._connected:
            self._connect_service_signals()
            self._connected = True
        # 刚显示时刷新一次，确保数据是最新的
        if hasattr(self, 'refresh_list'):
            self.refresh_list()

    def hideEvent(self, event):
        """窗口隐藏时断开信号连接，防止 WA_DeleteOnClose 对象
        在 C++ 层已销毁后仍收到信号导致 RuntimeError"""
        super().hideEvent(event)
        self._disconnect_service_signals()
        self._connected = False

    def closeEvent(self, event):
        """确保关闭时一定断开连接"""
        self._disconnect_service_signals()
        self._connected = False
        super().closeEvent(event)

    def _connect_service_signals(self):
        """子类可重写以连接特定信号"""
        self.service.schedules_changed.connect(self._on_schedules_changed)
        self.service.checkins_changed.connect(self._on_checkins_changed)

    def _disconnect_service_signals(self):
        """断开所有 service 信号。关键：防止 C++ 对象已销毁后收到信号闪退"""
        try:
            self.service.schedules_changed.disconnect(self._on_schedules_changed)
        except TypeError:
            pass  # 已经断开或从未连接
        try:
            self.service.checkins_changed.disconnect(self._on_checkins_changed)
        except TypeError:
            pass

    def _on_schedules_changed(self):
        if hasattr(self, 'refresh_list') and self.isVisible():
            self.refresh_list()

    def _on_checkins_changed(self):
        if hasattr(self, 'refresh_list') and self.isVisible():
            self.refresh_list()
```

**生命周期管理要点：**
- 信号在 `showEvent` 连接、`hideEvent` 断开 —— 窗口不可见时不响应
- `closeEvent` 强制断开 —— `WA_DeleteOnClose` 窗口的最终防线
- 使用 `try/except TypeError` 安全断开 —— 幂等、不抛异常

### 各 Dialog 变更

| Dialog | 原构造 | 新构造 | 备注 |
|--------|--------|--------|------|
| `ScheduleDialog` | `__init__(self, parent_pet)` | `__init__(self, service, parent=None)` | 继承 CalendarDialog |
| `MiniCalendarDialog` | 同上 | 同上 | 同上 |
| `CheckinDialog` | 同上 | 同上 | 同上 |
| `DayDetailDialog` | 同上 | 同上 | 同上 |
| `StatsDialog` | 同上 | 同上 | 同上 |
| `EditScheduleDialog` | `__init__(self, parent, sched=None, …)` | `__init__(self, service, parent, sched=None, …)` | 编辑框，不继承 CalendarDialog（无需自动刷新） |
| `EditCheckinDialog` | `__init__(self, parent, item=None)` | `__init__(self, service, parent, item=None)` | 同上 |
| `ScheduleAlertDialog` | `__init__(self, task_name, parent_pet, detail="")` | 保持当前签名 | 提醒弹窗由 oc.py 的队列系统创建 |
| `CheckinAlertDialog` | `__init__(self, item, parent_pet)` | 保持当前签名 | 同上 |

### 之前 vs 之后示例

```python
# === 之前：Dialog 直接操作 config 字典 ===
class EditScheduleDialog(QDialog):
    def save(self):
        # ...
        if self.is_new:
            data.update({"id": new_id(), "status": "pending", ...})
            self.pet.config.setdefault("schedules", []).append(data)  # ❌ UI 直接写 config
        else:
            self.sched.update(data)  # ❌ UI 直接修改字典
        self.accept()
        QTimer.singleShot(0, lambda: (
            save_config(pet.config),             # ❌ UI 调 save
            pet.refresh_dialogs(...)))           # ❌ UI 管刷新

# === 之后：UI 只收集数据，Service 处理一切 ===
class EditScheduleDialog(QDialog):
    def save(self):
        data = self._collect_form_data()  # 只收集用户输入
        if self.is_new:
            self.service.add_schedule(data)       # ✅ Service 负责原子操作
        else:
            self.service.update_schedule(self.sched, data)  # ✅ Service 负责原子操作
        self.accept()
        # 不需要 QTimer.singleShot，不需要 refresh_dialogs
        # Service 内部 save + emit signals → 各窗口自动刷新
```

## oc.py 变更

从 DesktopPet 中移除：
- `mark_schedule_done()` → CalendarService
- `do_checkin()` → CalendarService
- `check_checkin_bonus()` → CalendarService (private)
- `check_milestones()` → CalendarService (private)
- `build_plan_text()` → CalendarService
- `speak_today_plan()` → 保留在 pet（它依赖 send_msg / AI），改为调 `self.calendar_service.build_plan_text(d)` 获取数据
- `daily_rollover()` → CalendarService
- `MILESTONES` 常量 → CalendarService
- `refresh_dialogs()` → 保留在 pet（它是窗口管理，不是日历业务）

新增：
```python
# 在 DesktopPet.__init__ 中
self.calendar_service = CalendarService(self.config)

# 连接 UI 反馈信号
self.calendar_service.bubble_needed.connect(self.show_bubble)
self.calendar_service.ai_speech_needed.connect(self.inject_system_event)
self.calendar_service.coins_changed.connect(self._on_coins_changed)
self.calendar_service.milestone_reached.connect(self._on_milestone_reached)
```

`open_dialog()` 更新：传入 `self.calendar_service` 而非完整 pet。

## 测试

CalendarService 可脱离 Qt 单测（service 本身是 QObject，但发射信号的副作用在单测中可忽略或 assert）：

```python
import pytest
from datetime import date
from core.calendar_service import CalendarService

@pytest.fixture
def empty_config():
    return {"schedules": [], "checkins": [], "coins": 0, "stats": {}}

class TestScheduleWrite:
    def test_add_schedule(self, empty_config):
        svc = CalendarService(empty_config)
        sid = svc.add_schedule({"task": "测试", "time": "09:00", "category": "日待办"})
        assert len(empty_config["schedules"]) == 1
        assert empty_config["schedules"][0]["id"] == sid
        assert empty_config["schedules"][0]["status"] == "pending"

    def test_update_schedule(self, empty_config):
        svc = CalendarService(empty_config)
        sid = svc.add_schedule({"task": "测试"})
        sched = empty_config["schedules"][0]
        svc.update_schedule(sched, {"task": "修改后"})
        assert empty_config["schedules"][0]["task"] == "修改后"
        assert empty_config["schedules"][0]["notified"] == False  # 重置提醒

    def test_delete_schedule(self, empty_config):
        svc = CalendarService(empty_config)
        sid = svc.add_schedule({"task": "测试"})
        svc.delete_schedule(sid)
        assert len(empty_config["schedules"]) == 0

    def test_mark_done_awards_coins(self, empty_config):
        svc = CalendarService(empty_config)
        sid = svc.add_schedule({"task": "测试"})
        sched = empty_config["schedules"][0]
        svc.mark_schedule_done(sched, date.today(), True)
        assert empty_config["coins"] == 20
        assert empty_config["stats"]["todo_done_total"] == 1

    def test_undo_reclaims_coins(self, empty_config):
        svc = CalendarService(empty_config)
        sid = svc.add_schedule({"task": "测试"})
        sched = empty_config["schedules"][0]
        svc.mark_schedule_done(sched, date.today(), True)
        svc.mark_schedule_done(sched, date.today(), False)
        assert empty_config["coins"] == 0
        assert empty_config["stats"]["todo_done_total"] == 0

    def test_milestone_at_100_todo(self, empty_config):
        empty_config["stats"]["todo_done_total"] = 99
        svc = CalendarService(empty_config)
        sid = svc.add_schedule({"task": "测试"})
        svc.mark_schedule_done(empty_config["schedules"][0], date.today(), True)
        # coins 应该包含 20 (完成) + milestone bonus
        assert empty_config["coins"] > 20
        assert empty_config["stats"]["milestone_todo"] == 100

class TestCheckinWrite:
    def test_all_done_bonus_once_per_day(self, empty_config):
        ...

    def test_checkin_streak(self, empty_config):
        ...
```

## 文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/calendar_service.py` | **新增** | CalendarService 类 ~300 行 |
| `oc.py` | 修改 | 移除 ~10 个方法，创建 service，连信号 |
| `dialogs/calendar.py` | 修改 | 新增 CalendarDialog 基类，self.pet→self.service，不直接操作 config |
| `core/utils.py` | 不改 | 纯函数保持现状 |
| `tests/test_calendar_service.py` | **新增** | 业务逻辑单测 |

## 实施顺序

1. 创建 `core/calendar_service.py`：从 oc.py 搬业务逻辑 + 新增增删改原子方法
2. 写 `tests/test_calendar_service.py`，确认所有业务逻辑正确
3. 修改 `oc.py`：创建 service 实例，连接 UI 反馈信号，移除已迁移的方法
4. 在 `dialogs/calendar.py` 新增 `CalendarDialog` 基类（含生命周期管理）
5. 逐个改造 dialog：构造器接收 service → 写操作调 service 方法 → 移除 config 直接操作
6. 验证：跑单测通过 + 手动流程验证

## 不做什么

- 不改变 `core/utils.py` 的纯函数
- 不改变 config.json 的数据格式
- 不改 ebook.py 除非它直接调了 pet 的日历方法
- 不引入新的第三方依赖
- MVP 阶段用全局刷新信号，不做 item 级局部更新（当前数据量下开销可忽略）
