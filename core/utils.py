import calendar as _pycalendar
import random
import time
from datetime import date, datetime, timedelta

_ID_SEQ = [0]

REPEAT_LABELS = [
    ("once", "不重复（仅这一天）"),
    ("daily", "每天"),
    ("weekly", "每周"),
    ("monthly", "每月"),
    ("yearly", "每年"),
    ("custom", "自定义间隔（天）"),
]

REPEAT_KEYS = [k for k, _ in REPEAT_LABELS]

REPEAT_TEXT = dict(REPEAT_LABELS)

CATEGORIES = ["日待办", "周待办", "月待办", "长期"]

def new_id():
    _ID_SEQ[0] += 1
    return int(time.time() * 1000) * 1000 + (_ID_SEQ[0] % 1000)

def today_str():
    return date.today().strftime("%Y-%m-%d")

def parse_date(s):
    """把 'YYYY-MM-DD' 转成 date；失败返回 None（绝不抛异常）"""
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None

def _clamp_day(y, m, d):
    """把 31 号安全地放进只有 28/30 天的月份"""
    last = _pycalendar.monthrange(y, m)[1]
    return min(d, last)

def sched_occurs_on(sched, d):
    """判断某条日程是否发生在日期 d 上。无日期的日程视为‘每天都算’。"""
    if not isinstance(sched, dict):
        return False
    anchor = parse_date(sched.get("date", ""))
    if anchor is None:
        return True  # 没绑定日期 = 每天都出现（与老版本行为一致）
    if d < anchor:
        return False
    rep = sched.get("repeat", "once")
    if rep == "once":
        return d == anchor
    if rep == "daily":
        return True
    if rep == "weekly":
        return (d - anchor).days % 7 == 0
    if rep == "monthly":
        return d.day == _clamp_day(d.year, d.month, anchor.day)
    if rep == "yearly":
        return d.month == anchor.month and d.day == _clamp_day(d.year, anchor.month, anchor.day)
    if rep == "custom":
        try:
            n = max(1, int(sched.get("repeat_days", 1)))
        except Exception:
            n = 1
        return (d - anchor).days % n == 0
    return d == anchor

def sched_is_recurring(sched):
    """是否是‘会反复出现’的日程（需要按天分别记录完成情况）"""
    if not parse_date(sched.get("date", "")):
        return False  # 无日期的沿用老的 status 逻辑，保证旧数据行为不变
    return sched.get("repeat", "once") != "once"

def sched_done_on(sched, d):
    """某条日程在日期 d 是否已完成"""
    if sched_is_recurring(sched):
        return d.strftime("%Y-%m-%d") in (sched.get("done_dates") or [])
    return sched.get("status") == "completed"

def sched_set_done(sched, d, done=True):
    """标记完成 / 取消完成，返回是否真的发生了变化"""
    key = d.strftime("%Y-%m-%d")
    if sched_is_recurring(sched):
        lst = sched.setdefault("done_dates", [])
        if done and key not in lst:
            lst.append(key)
            # 只保留最近 400 天，防止长期使用后存档越滚越大
            if len(lst) > 400:
                del lst[:-400]
            return True
        if not done and key in lst:
            lst.remove(key)
            return True
        return False
    else:
        old = sched.get("status")
        if done and old != "completed":
            sched["status"] = "completed"
            sched["completed_time"] = datetime.now().strftime("%m-%d %H:%M")
            sched["completed_date"] = d.strftime("%Y-%m-%d")
            return True
        if not done and old == "completed":
            sched["status"] = "pending"
            sched.pop("completed_time", None)
            sched.pop("completed_date", None)
            return True
        return False

def schedules_of_day(config, d, include_hidden=False):
    """取出某一天要做的全部日程（已按时间排序）"""
    out = []
    for s in config.get("schedules", []):
        if not isinstance(s, dict):
            continue
        if not include_hidden and s.get("status") == "hidden":
            continue
        # 未绑定日期的是“通用待办”：它每天到点仍可提醒，但只放进今天的日历。
        # 否则只要存在一条通用待办，整个月 42 个格子都会被染蓝，历史统计也会
        # 把同一条待办重复算几十次。已经完成的通用待办只记在实际完成那一天。
        if parse_date(s.get("date", "")) is None:
            completed_on = parse_date(s.get("completed_date", ""))
            if d != date.today() and d != completed_on:
                continue
        if sched_occurs_on(s, d):
            out.append(s)
    out.sort(key=lambda x: str(x.get("time", "99:99")))
    return out

def checkin_done_on(item, d):
    return d.strftime("%Y-%m-%d") in (item.get("done_dates") or [])

def checkin_set_done(item, d, done=True):
    key = d.strftime("%Y-%m-%d")
    lst = item.setdefault("done_dates", [])
    if done and key not in lst:
        lst.append(key)
        lst.sort()
        if len(lst) > 400:
            del lst[:-400]
        return True
    if not done and key in lst:
        lst.remove(key)
        return True
    return False

def active_checkins(config):
    return [c for c in config.get("checkins", [])
            if (isinstance(c, dict)
                and not c.get("archived", False)
                and c.get("enabled", True))]

def checkin_streak(item, today=None):
    """连续打卡天数（今天没打也算‘昨天结束的连击’，不会显示成 0 打击积极性）"""
    d = today or date.today()
    done = set(item.get("done_dates") or [])
    if not done:
        return 0
    if d.strftime("%Y-%m-%d") not in done:
        d = d - timedelta(days=1)
    n = 0
    while d.strftime("%Y-%m-%d") in done:
        n += 1
        d -= timedelta(days=1)
    return n

def migrate_config(cfg):
    """
    老存档 → 新版本的一次性升级。
    原则：只补字段、不删数据、不改变已有条目的显示效果。
    """
    changed = False
    # 兼容 0.1.6 日历试验版的字段名称。
    # 当时使用 daily_checkins/title/last_done，新版统一为 checkins/name/done_dates。
    legacy_checkins = cfg.get("daily_checkins", [])
    if isinstance(legacy_checkins, list) and legacy_checkins:
        current_checkins = cfg.setdefault("checkins", [])
        if not isinstance(current_checkins, list):
            current_checkins = []
            cfg["checkins"] = current_checkins
            changed = True
        migrated_keys = {
            c.get("_legacy_daily_checkin_key")
            for c in current_checkins if isinstance(c, dict)
        }
        existing_ids = {
            c.get("id") for c in current_checkins
            if isinstance(c, dict) and c.get("id") is not None
        }
        existing_names = {
            str(c.get("name", "")).strip() for c in current_checkins
            if isinstance(c, dict)
        }
        for old in legacy_checkins:
            if not isinstance(old, dict):
                continue
            name = old.get("name") or old.get("title") or "未命名打卡"
            legacy_key = (
                f"id:{old.get('id')}" if old.get("id") is not None
                else f"name:{str(name).strip()}"
            )
            if (legacy_key in migrated_keys
                    or (old.get("id") is not None and old.get("id") in existing_ids)
                    or str(name).strip() in existing_names):
                continue
            done_dates = []
            if parse_date(old.get("last_done", "")):
                done_dates.append(str(old["last_done"])[:10])
            current_checkins.append({
                "id": old.get("id", new_id()),
                "name": name,
                "note": old.get("note", ""),
                "enabled": old.get("enabled", True),
                "archived": old.get("archived", False),
                "remind_times": old.get("remind_times", []),
                "created": old.get("created", today_str()),
                "done_dates": done_dates,
                "_legacy_daily_checkin_key": legacy_key,
            })
            migrated_keys.add(legacy_key)
            existing_ids.add(current_checkins[-1]["id"])
            existing_names.add(str(name).strip())
            changed = True

    seen_ids = set()
    for s in cfg.get("schedules", []):
        if not isinstance(s, dict):
            continue
        for k, v in (("category", "日待办"), ("status", "pending"), ("alarm_on", True),
                     ("time", "09:00"), ("task", "未命名待办"), ("date", ""),
                     ("repeat", "once"), ("repeat_days", 1), ("note", "")):
            if k not in s:
                s[k] = v
                changed = True
        if "done_dates" not in s:
            s["done_dates"] = []
            changed = True
        if s.get("status") == "completed" and not s.get("completed_date"):
            # 旧版只保存“月-日 时:分”，缺少年份。优先恢复该日期；无法判断时
            # 至少记为今天，避免统计把这一条算到过去和未来的每一天。
            old_done = str(s.get("completed_time", ""))
            try:
                month, day = map(int, old_done[:5].split("-"))
                candidate = date(date.today().year, month, day)
                if candidate > date.today():
                    candidate = date(candidate.year - 1, month, day)
                s["completed_date"] = candidate.strftime("%Y-%m-%d")
            except Exception:
                s["completed_date"] = today_str()
            changed = True
        # 兼容 0.1.6 试验版保存的中文重复规则和 custom_interval 字段。
        repeat_map = {
            "不重复": "once", "每日": "daily", "每天": "daily",
            "每周": "weekly", "每月": "monthly", "每年": "yearly",
            "自定义间隔(天)": "custom", "自定义间隔（天）": "custom",
        }
        old_repeat = s.get("repeat", "once")
        if old_repeat in repeat_map:
            s["repeat"] = repeat_map[old_repeat]
            changed = True
        if "custom_interval" in s and (
                "repeat_days" not in s or s.get("repeat_days") in (None, 1)):
            try:
                s["repeat_days"] = max(1, int(s["custom_interval"]))
            except Exception:
                s["repeat_days"] = 1
            changed = True
        # id 缺失或撞号，一律重发
        if "id" not in s or s["id"] in seen_ids:
            s["id"] = new_id()
            changed = True
        seen_ids.add(s["id"])

    for c in cfg.get("checkins", []):
        if not isinstance(c, dict):
            continue
        for k, v in (("name", "未命名打卡"), ("note", ""), ("enabled", True),
                     ("archived", False), ("remind_times", []), ("created", today_str())):
            if k not in c:
                c[k] = v
                changed = True
        if "done_dates" not in c:
            c["done_dates"] = []
            changed = True
        if "id" not in c or c["id"] in seen_ids:
            c["id"] = new_id()
            changed = True
        seen_ids.add(c["id"])

    nid = set()
    for n in cfg.get("notes", []):
        if isinstance(n, dict) and ("id" not in n or n["id"] in nid):
            n["id"] = new_id()
            changed = True
        if isinstance(n, dict):
            nid.add(n.get("id"))
    return changed
