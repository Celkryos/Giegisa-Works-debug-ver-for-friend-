"""nl_parser.py — 从 AI 回复中健壮地提取日程创建意图

解析 [SCHEDULE_JSON]...[/SCHEDULE_JSON] 标记块，容忍常见格式错误。
纯函数，不依赖 PyQt。
"""

import re
import json

_TAG_OPEN = "[SCHEDULE_JSON]"
_TAG_CLOSE = "[/SCHEDULE_JSON]"

# 有效的 repeat 值
_VALID_REPEATS = {"once", "daily", "weekly", "monthly", "yearly", "custom"}

# 时间格式校验
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")

# 日期格式校验
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def extract_schedule_intents(text: str) -> list[dict]:
    """从 AI 回复中提取所有日程创建意图。

    返回 list[dict]，每个 dict 至少包含 "task" 键。
    失败或未找到时返回空列表。
    """
    if not text or _TAG_OPEN not in text:
        return []

    results = []
    pos = 0

    while True:
        start = text.find(_TAG_OPEN, pos)
        if start == -1:
            break

        content_start = start + len(_TAG_OPEN)
        end = text.find(_TAG_CLOSE, content_start)

        if end != -1:
            # ── 正常闭合 ──
            json_str = text[content_start:end]
            pos = end + len(_TAG_CLOSE)
        else:
            # ── 未闭合：从 content_start 到文本末尾（或下一个开始标签） ──
            next_start = text.find(_TAG_OPEN, content_start)
            if next_start != -1:
                json_str = text[content_start:next_start]
                pos = next_start
            else:
                json_str = text[content_start:]
                pos = len(text)

            # 推断 JSON 边界：从后往前找最后一个 }
            last_brace = json_str.rfind("}")
            if last_brace != -1:
                json_str = json_str[: last_brace + 1]

        if not json_str or not json_str.strip():
            continue

        parsed = _robust_parse_json(json_str)
        if parsed and _validate_schedule(parsed):
            results.append(_normalize(parsed))

    return results


def strip_schedule_tags(text: str) -> str:
    """移除 AI 回复中的日程标记块，返回纯文本。"""
    if not text or _TAG_OPEN not in text:
        return text

    # 移除所有 [SCHEDULE_JSON]...[/SCHEDULE_JSON] 块
    pattern = re.compile(
        re.escape(_TAG_OPEN) + r".*?" + re.escape(_TAG_CLOSE),
        re.DOTALL,
    )
    cleaned = pattern.sub("", text)

    # 也处理未闭合的情况（不太可能但防御性处理）
    cleaned = re.sub(re.escape(_TAG_OPEN) + r".*", "", cleaned, flags=re.DOTALL)

    # 清理多余空行
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()

    return cleaned


# ── 内部 ──────────────────────────────────────────


def _robust_parse_json(s: str) -> dict | None:
    """多层 fallback 的 JSON 解析。"""
    s = s.strip()

    # 1. 移除可能的 markdown 代码块包装
    s = _unwrap_markdown_code(s)

    # 2. 直接解析
    result = _try_json_loads(s)
    if result:
        return result

    # 3. 修复尾部多余逗号后重试
    fixed = re.sub(r",\s*}", "}", s)
    fixed = re.sub(r",\s*]", "]", fixed)
    result = _try_json_loads(fixed)
    if result:
        return result

    # 4. 提取第一个平衡的 {...} 对象
    result = _extract_first_json_object(s)
    if result:
        return result

    # 5. 最后的尝试：正则提取关键字段
    return _regex_extract_fields(s)


def _unwrap_markdown_code(s: str) -> str:
    """移除 ```json ... ``` 包装。"""
    s = s.strip()
    if s.startswith("```"):
        # 找第一行结束
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1 :]
        else:
            s = s[3:]  # 只有 ```，去掉
    if s.endswith("```"):
        s = s[: -3]
    return s.strip()


def _try_json_loads(s: str) -> dict | None:
    """尝试 json.loads，失败返回 None。"""
    if not s or s[0] not in "{[":
        return None
    try:
        result = json.loads(s)
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
            return result[0]  # 数组包裹的单个对象
        return None
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_first_json_object(s: str) -> dict | None:
    """扫描文本，提取第一个平衡的 {} 对象。"""
    # 找到第一个 {
    start_idx = s.find("{")
    if start_idx == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start_idx, len(s)):
        ch = s[i]

        if escape_next:
            escape_next = False
            continue

        if ch == "\\":
            escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = s[start_idx : i + 1]
                return _try_json_loads(candidate)

    return None


def _regex_extract_fields(s: str) -> dict | None:
    """用正则逐个提取字段，作为最后的兜底方案。"""
    task = _extract_str_field(s, "task")
    if not task:
        return None

    result = {"task": task}

    time_val = _extract_str_field(s, "time")
    if time_val:
        result["time"] = time_val

    date_val = _extract_str_field(s, "date")
    if date_val:
        result["date"] = date_val

    note_val = _extract_str_field(s, "note")
    if note_val:
        result["note"] = note_val

    repeat_val = _extract_str_field(s, "repeat")
    if repeat_val:
        result["repeat"] = repeat_val

    return result


def _extract_str_field(s: str, field: str) -> str | None:
    """正则提取 "field": "value" 或 "field":"value"。"""
    # 匹配 "field": "value" (允许值中有转义引号)
    pattern = rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)"'
    m = re.search(pattern, s)
    if m:
        val = m.group(1)
        # 反转义
        val = val.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
        return val
    return None


# ── 校验 & 标准化 ──────────────────────────────────


def _validate_schedule(data: dict) -> bool:
    """检查解析结果是否至少包含有效的 task 字段。"""
    if not isinstance(data, dict):
        return False
    task = data.get("task")
    return bool(task) and isinstance(task, str) and task.strip()


def _normalize(data: dict) -> dict:
    """标准化日程字段，补默认值、格式清洗。"""
    result = {
        "task": str(data.get("task", "")).strip(),
        "time": _norm_time(data.get("time", "")),
        "date": _norm_date(data.get("date", "")),
        "note": str(data.get("note", "")).strip()[:200],
        "repeat": _norm_repeat(data.get("repeat", "once")),
    }
    return result


def _norm_time(val) -> str:
    """标准化时间 → HH:MM，无效时返回空字符串。"""
    s = str(val).strip()
    if _TIME_RE.match(s):
        return s
    # 尝试宽松匹配
    m = re.match(r"(\d{1,2})[:：](\d{2})", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"
    return ""


def _norm_date(val) -> str:
    """标准化日期 → YYYY-MM-DD，无效/空时返回空字符串。"""
    s = str(val).strip()
    if not s:
        return ""
    if _DATE_RE.match(s):
        return s
    return ""


def _norm_repeat(val) -> str:
    """标准化重复规则。"""
    s = str(val).strip().lower()
    if s in _VALID_REPEATS:
        return s
    # 中文映射
    zh_map = {
        "不重复": "once",
        "每天": "daily",
        "每日": "daily",
        "每周": "weekly",
        "每月": "monthly",
        "每年": "yearly",
        "自定义": "custom",
    }
    return zh_map.get(s, "once")
