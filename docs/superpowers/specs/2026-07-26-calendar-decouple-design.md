# Calendar 模块三层解耦 — 设计文档

日期：2026-07-26

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
  ├─ 各 Dialog: 纯 Qt UI
  ├─ 通过 self.service 调用业务方法
  └─ 连接 service 信号 → self.refresh_list()

core/calendar_service.py (逻辑层) ★新增★
  ├─ CalendarService(QObject)
  ├─ 持有 config 引用
  ├─ 所有日程/打卡业务方法
  └─ 发射信号通知变更

core/utils.py (数据层) 已有，不改
  └─ schedules_of_day, sched_done_on 等纯函数
```

## CalendarService 设计

### 构造

```python
class CalendarService(QObject):
    def __init__(self, config: dict, parent=None):
        self.config = config
```

`config` 是 mutable dict，DesktopPet 持有同一份引用。Service 直接修改 config，不再需要传回给 pet。

### 公开方法

| 方法 | 参数 | 返回值 | 副作用 |
|------|------|--------|--------|
| `mark_schedule_done(sched, d, done)` | sched dict, date, bool | bool (是否变化) | 更新金币、里程碑、发射信号 |
| `do_checkin(item, d, done, quiet)` | item dict, date, bool, bool | bool | 更新金币、检查全勤、里程碑、发射信号 |
| `build_plan_text(d)` | date | str | 无 |
| `schedules_of_day(d)` | date | list[dict] | 无 |
| `active_checkins()` | — | list[dict] | 无 |
| `checkin_streak(item)` | dict | int | 无 |
| `get_stats(days)` | int | dict | 无 |
| `save()` | — | — | 调用 save_config(config) |

### 信号

```python
schedules_changed = pyqtSignal()
checkins_changed = pyqtSignal()
coins_changed = pyqtSignal(int)          # new_amount
milestone_reached = pyqtSignal(str, int) # label, count  
bubble_needed = pyqtSignal(str)          # 格式化文本 → show_bubble
ai_speech_needed = pyqtSignal(str, str)  # (user_action, ai_response) → inject_system_event
checkin_bonus_earned = pyqtSignal(int)   # bonus_amount
```

### 关键方法逻辑（从 oc.py 迁移）

#### mark_schedule_done

```
1. 调 core.utils.sched_set_done(sched, d, done) — 纯数据操作
2. 如果标记为完成:
   - stats.todo_done_total += 1
   - config.coins += 20
   - emit coins_changed
   - emit ai_speech_needed("系统：用户完成待办...", "【normal】...")
3. 如果撤销:
   - stats.todo_done_total -= 1  
   - config.coins -= 20
4. save()
5. emit schedules_changed
6. 调 _check_milestones() — 内部检查是否触发里程碑
```

#### do_checkin

```
1. 调 core.utils.checkin_set_done(item, d, done)
2. 如果标记为完成:
   - stats.checkin_done_total += 1
   - config.coins += 5
   - 检查全勤奖励 (_check_checkin_bonus)
3. 否则撤销
4. save()
5. emit checkins_changed
6. _check_milestones()
```

## oc.py 变更

从 DesktopPet 中移除这些方法：
- `mark_schedule_done()` → CalendarService
- `do_checkin()` → CalendarService
- `check_checkin_bonus()` → CalendarService (private)
- `check_milestones()` → CalendarService (private)
- `build_plan_text()` → CalendarService
- `speak_today_plan()` → CalendarService (部分逻辑保留在 pet 来调 send_msg)
- `daily_rollover()` → CalendarService
- `MILESTONES` 常量 → CalendarService

新增：
- `self.calendar_service = CalendarService(self.config)`
- 连接 service 信号到 pet 的 UI 方法

`open_dialog()` 方法更新：传入 service 而非完整 pet 对象。

## dialogs/calendar.py 变更

### 统一的 Dialog 基类模式

```python
class CalendarDialog(QDialog):
    """所有 calendar dialog 的基类"""
    def __init__(self, service: CalendarService, parent=None):
        super().__init__(parent)
        self.service = service
        self.service.schedules_changed.connect(self._on_data_changed)
        self.service.checkins_changed.connect(self._on_data_changed)
    
    def _on_data_changed(self):
        if self.isVisible() and hasattr(self, 'refresh_list'):
            self.refresh_list()
```

### 各 Dialog 变更

- `ScheduleDialog`：`parent_pet` → `service, parent`
- `MiniCalendarDialog`：同上
- `CheckinDialog`：同上
- `DayDetailDialog`：同上
- `StatsDialog`：同上
- `EditScheduleDialog`：同上
- `EditCheckinDialog`：同上
- `ScheduleAlertDialog` / `CheckinAlertDialog`：保持不变（提醒弹窗，创建方式不同）

### 之前 vs 之后示例

```python
# 之前
class ScheduleDialog(QDialog):
    def __init__(self, parent_pet):
        super().__init__(parent_pet)
        self.pet = parent_pet
        # ...
    def mark_done(self, sched, done=True):
        self.pet.mark_schedule_done(sched, date.today(), done)
        self.refresh_list()

# 之后
class ScheduleDialog(CalendarDialog):
    def __init__(self, service, parent=None):
        super().__init__(service, parent)
        # ...
    def mark_done(self, sched, done=True):
        self.service.mark_schedule_done(sched, date.today(), done)
        # refresh_list 由 service.schedules_changed 信号自动触发
```

## 测试

CalendarService 可脱离 Qt 单测：

```python
def test_mark_done_awards_coins():
    config = {"schedules": [{"id": "1", "task": "test", "status": "pending"}], 
              "coins": 0, "stats": {}}
    service = CalendarService(config)
    service.mark_schedule_done(config["schedules"][0], date.today(), True)
    assert config["coins"] == 20
    assert config["stats"]["todo_done_total"] == 1

def test_undo_reclaims_coins():
    ...

def test_milestone_100_todo():
    ...

def test_checkin_all_done_bonus():
    ...

def test_build_plan_text():
    ...
```

## 文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/calendar_service.py` | **新增** | CalendarService 类 |
| `oc.py` | 修改 | 移除业务方法，创建 service，连信号 |
| `dialogs/calendar.py` | 修改 | self.pet → self.service |
| `dialogs/ebook.py` | 可能修改 | 如果 ebook 调了 pet.mark_schedule_done 等 |
| `core/utils.py` | 不改 | 纯函数保持现状 |
| `tests/test_calendar_service.py` | **新增** | 业务逻辑单测 |

## 实施顺序

1. 创建 `CalendarService` 类，从 oc.py 搬业务逻辑
2. 写单测，确认业务逻辑正确
3. 修改 oc.py：创建 service 实例，连信号
4. 修改 calendar.py：self.pet → self.service，逐个 dialog 改
5. 验证：跑单测 + 手动跑完整流程

## 不做什么

- 不改变 `core/utils.py` 的纯函数——它们已经很好
- 不改变 config.json 的数据格式
- 不改 ebook.py 除非它直接调用了 pet 的日历方法
- 不引入新的第三方依赖
