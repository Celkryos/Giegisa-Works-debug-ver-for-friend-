import sys
import os
import random
import time
import re
import json
import ctypes
import winsound
import base64
import urllib.request
import urllib.error
import calendar as _pycalendar
import shutil
from datetime import datetime, date, timedelta
from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QMenu, QLineEdit, QVBoxLayout, QHBoxLayout, QDialog, QListWidget, QPushButton, QListWidgetItem, QTextEdit, QMessageBox, QFormLayout, QSpinBox, QColorDialog, QComboBox, QGroupBox, QFileDialog, QTimeEdit, QSizePolicy, QInputDialog, QSystemTrayIcon, QCheckBox, QGridLayout, QDateEdit, QScrollArea)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QPoint, QTime, QByteArray, QBuffer, QIODevice, QDate
from PyQt6.QtGui import QPixmap, QColor, QAction, QCursor, QIcon, QImage

from config import (BASE_DIR, PIC_DIR, UI_BACKGROUND_FILE, CONFIG_FILE, HISTORY_FILE, NOTES_FILE, DEFAULT_CONFIG, LOAD_WARNINGS, safe_json_save, _atomic_write_json, _read_json, load_config, save_config, flush_config_if_dirty)
from core.utils import *
from api import gemini_rest_generate, openai_chat
from threads import ChatThread, TriviaThread, IdleChatThread, RandomEventThread, DataRetrievalThread, ItemRetrievalThread, ImageFetchThread
from ui import MENU_QSS, ImageBubble, ResponsiveListWidget, DraggableListWidget, ChatInputBox, FocusOverlay, InputDialog, install_ice_glass_theme
from dialogs import (UserProfileDialog, MoodDialog, ScheduleAlertDialog, CheckinAlertDialog, EditScheduleDialog, EditCheckinDialog, ScheduleDialog, DayDetailDialog, MiniCalendarDialog, CheckinDialog, StatsDialog, CollectionManagerDialog, EditNoteDialog, QuickNoteDialog, NotesManagerDialog, DistractionSettingsDialog, AutoEventSettingsDialog, RandomEventDialog, StoreDialog, ApiSettingsDialog, AppearanceDialog, FocusDialog, MemorySettingsDialog, HistoryDialog, EbookShelfDialog)

_EMOTION_TOKEN_RE = re.compile(
    r"[*_]*[\[【\(（\{]\s*(normal|shy|angry|dark)\s*[\]】\)）\}][*_]*",
    re.IGNORECASE,
)
_PRIVATE_PROMPT_RE = re.compile(
    r"[\[【](?:系统后台强制指令|后台强制潜意识|后台状态干预|"
    r"事实数据(?:·[^】\]]*)?|情绪状态)[\s\S]*?[\]】]",
    re.IGNORECASE,
)


def sanitize_bubble_text(text):
    """清除情绪控制符和模型偶尔复述出的后台提示，不伤普通中文括号。"""
    value = str(text or "")
    value = re.sub(r"<think>[\s\S]*?</think>", "", value, flags=re.IGNORECASE)
    value = _PRIVATE_PROMPT_RE.sub("", value)
    value = _EMOTION_TOKEN_RE.sub("", value)
    value = re.sub(
        r"^\s*(?:emotion|情绪标签)\s*[:：]\s*(?:normal|shy|angry|dark)\s*[\r\n]*",
        "", value, flags=re.IGNORECASE)
    value = re.sub(
        r"^\s*(?:normal|shy|angry|dark)\s*[:：\-—]\s*",
        "", value, flags=re.IGNORECASE)
    return value.strip()


class DesktopPet(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        
        self.scale_size = 200
        self.current_emotion = "normal"
        
        self.total_mood = self.config.get("total_mood", 50.0)
        if "mood_value" in self.config:
            self.session_mood = float(self.config["mood_value"])
            self.total_mood = float(self.config["mood_value"])
            del self.config["mood_value"]
            self.config["total_mood"] = self.total_mood
            save_config(self.config)
        else:
            self.session_mood = 50.0 
        
        self.is_following = False
        self.mouse_drag_pos = QPoint()

        self.full_text = ""
        self.display_text = ""
        self.text_index = 0
        self.is_typing = False
        self.can_skip = True
        self.is_speaking = False
        
        self.is_focus_mode = False
        self.focus_type = "normal" 
        self.focus_seconds = 0
        self.focus_total_seconds = 0
        self.focus_start_dt = None
        self.focus_end_dt = None
        self.hourly_triggered = False
        self.focus_overlay = None 
        
        self.idle_seconds = 0   
        self.event_seconds = 0  
        self.note_seconds = 0   
        self._pending_dialog_refreshes = set()
        self._dialog_refresh_scheduled = False
        self._alert_queue = []
        self._active_alert = None
        self._alert_retry_pending = False
        self._shutting_down = False
        self._bubble_queue = []
        self._pending_type_interval = None
        self._bubble_hold_until = 0.0
        self._bubble_dispatch_pending = False
        
        self.init_images()
        self.init_ui()
        self.init_timers()
        
        self.chat_thread = ChatThread(self.config)
        self.chat_thread.reply_ready.connect(self.handle_api_reply)
        self.chat_thread.error_occurred.connect(self.handle_api_reply)
        self.chat_thread.api_lag_occurred.connect(self.handle_api_lag)
        self.chat_thread.summary_updated.connect(self.on_summary_updated)
        
        self.last_media_title = ""
        
        # ===== 生物电脉冲监测(鼠标/键盘计数，类似 bongo cat) =====
        self.session_clicks = 0
        self.session_keys = 0
        self._flushed_clicks = 0
        self._flushed_keys = 0
        self.global_input_hook_active = False
        self.init_input_counter()

        self.check_daily_signin()
        if LOAD_WARNINGS:
            warning_text = "\n".join(dict.fromkeys(LOAD_WARNINGS))
            QTimer.singleShot(
                800,
                lambda text=warning_text: QMessageBox.warning(
                    self, "存档自动恢复提示", text))

    def on_summary_updated(self, summary):
        """后台长期记忆更新后，安全刷新已打开的记忆设置窗口。"""
        dlg = getattr(self, "dlg_MemorySettingsDialog", None)
        if dlg is None or not hasattr(dlg, "summary_edit"):
            return
        try:
            dlg.summary_edit.setPlainText(summary)
        except RuntimeError:
            self.dlg_MemorySettingsDialog = None

    # ==========================================
    # 🔧 通用：刷新已经打开的面板
    #    原来每个地方都写一遍 for attr in dir(self)... 重复了 6 处，这里统一成一个方法
    # ==========================================
    def refresh_dialogs(self, *prefixes):
        """合并同一轮操作里的重复刷新，避免大量窗口同时重建列表卡住界面。"""
        self._pending_dialog_refreshes.update(prefixes or ("dlg_",))
        if self._dialog_refresh_scheduled:
            return
        self._dialog_refresh_scheduled = True
        QTimer.singleShot(0, self._flush_dialog_refreshes)

    def _flush_dialog_refreshes(self):
        self._dialog_refresh_scheduled = False
        prefixes = tuple(self._pending_dialog_refreshes)
        self._pending_dialog_refreshes.clear()
        for attr in list(self.__dict__.keys()):
            if not attr.startswith("dlg_"):
                continue
            if prefixes and not any(attr.startswith(p) for p in prefixes):
                continue
            dlg = self.__dict__.get(attr)
            if dlg is None:
                continue
            try:
                # 隐藏面板等下次显示时再刷新，避免用户看不到的重复工作。
                if dlg.isVisible() and hasattr(dlg, "refresh_list"):
                    dlg.refresh_list()
            except RuntimeError:
                # 窗口的 C++ 对象已被销毁，把这个坏引用清掉
                self.__dict__[attr] = None
            except Exception:
                pass

    def queue_reminder(self, kind, *payload):
        """提醒排队显示；模态窗口存在时暂缓，避免多个置顶窗口互相锁住。"""
        key = (kind, str(payload[0].get("id")) if kind == "checkin" else str(payload[0]))
        if key in [entry[0] for entry in self._alert_queue]:
            return
        self._alert_queue.append((key, kind, payload))
        self._try_show_next_reminder()

    def _try_show_next_reminder(self):
        if self._shutting_down or self._active_alert is not None or not self._alert_queue:
            return
        if QApplication.activeModalWidget() is not None:
            if not self._alert_retry_pending:
                self._alert_retry_pending = True
                QTimer.singleShot(300, self._retry_reminder)
            return
        _, kind, payload = self._alert_queue.pop(0)
        if kind == "schedule":
            dlg = ScheduleAlertDialog(payload[0], self, payload[1])
        else:
            dlg = CheckinAlertDialog(payload[0], self)
        self._active_alert = dlg
        dlg.finished.connect(self._reminder_finished)
        dlg.show()
        dlg.raise_()

    def _retry_reminder(self):
        self._alert_retry_pending = False
        self._try_show_next_reminder()

    def _reminder_finished(self, _result=0):
        self._active_alert = None
        QTimer.singleShot(0, self._try_show_next_reminder)

    # ==========================================
    # 📅 日程 / 打卡 / 统计 的核心逻辑
    # ==========================================
    def mark_schedule_done(self, sched, d=None, done=True):
        d = d or date.today()
        if not sched_set_done(sched, d, done):
            save_config(self.config)
            return
        st = self.config.setdefault("stats", {})
        if done:
            st["todo_done_total"] = st.get("todo_done_total", 0) + 1
            self.config["coins"] = self.config.get("coins", 0) + 20
            save_config(self.config)
            self.inject_system_event(
                f"系统：用户完成了待办事项 [{sched.get('task','')}]",
                f"【normal】计划执行得不错。 [{sched.get('task','')}] 已经从待办里划掉了。这是给你的20数据碎片。")
            self.check_milestones()
        else:
            st["todo_done_total"] = max(0, st.get("todo_done_total", 0) - 1)
            self.config["coins"] = max(0, self.config.get("coins", 0) - 20)
            save_config(self.config)
        self.refresh_dialogs("dlg_ScheduleDialog", "dlg_MiniCalendarDialog", "dlg_StatsDialog")

    def do_checkin(self, item, d=None, done=True, quiet=False):
        d = d or date.today()
        if not checkin_set_done(item, d, done):
            return
        st = self.config.setdefault("stats", {})
        if done:
            st["checkin_done_total"] = st.get("checkin_done_total", 0) + 1
            self.config["coins"] = self.config.get("coins", 0) + 5
        else:
            st["checkin_done_total"] = max(0, st.get("checkin_done_total", 0) - 1)
            self.config["coins"] = max(0, self.config.get("coins", 0) - 5)
        save_config(self.config)

        if done and d == date.today() and not quiet:
            self.check_checkin_bonus()
        if not quiet:
            self.check_milestones()
        self.refresh_dialogs("dlg_CheckinDialog", "dlg_MiniCalendarDialog", "dlg_StatsDialog")

    def check_checkin_bonus(self):
        """今天所有启用中的打卡都完成了 → 发一次额外奖励（每天只发一次）"""
        today = date.today()
        acts = [c for c in active_checkins(self.config) if c.get("enabled", True)]
        if not acts:
            return
        if not all(checkin_done_on(c, today) for c in acts):
            return
        if self.config.get("checkin_last_bonus_date") == today.strftime("%Y-%m-%d"):
            return
        bonus = random.randint(30, 60)
        self.config["checkin_last_bonus_date"] = today.strftime("%Y-%m-%d")
        self.config["coins"] = self.config.get("coins", 0) + bonus
        save_config(self.config)
        self.change_mood(5)
        self.inject_system_event(
            f"系统：用户今日打卡全部完成，获得{bonus}数据碎片全勤奖励",
            f"【shy】……今天的{len(acts)}项打卡一个没落。哼，算你有点自律。"
            f"额外奖励 <font color='#FFD700'>{bonus} 数据碎片</font>，拿好。")

    MILESTONES = [10, 30, 50, 100, 200, 300, 500, 800, 1000, 1500, 2000, 3000, 5000]

    def check_milestones(self):
        """累计完成量跨过里程碑时，让 Giegisa 说句话并给随机碎片奖励"""
        st = self.config.setdefault("stats", {})
        for key, reached_key, label in (("todo_done_total", "milestone_todo", "待办"),
                                        ("checkin_done_total", "milestone_checkin", "打卡")):
            total = st.get(key, 0)
            reached = st.get(reached_key, 0)
            new_mark = None
            for m in self.MILESTONES:
                if total >= m > reached:
                    new_mark = m
            if new_mark is None:
                continue
            st[reached_key] = new_mark
            reward = random.randint(50, 150)
            self.config["coins"] = self.config.get("coins", 0) + reward
            save_config(self.config)
            self.change_mood(8)
            self.inject_system_event(
                f"系统：用户累计完成{label}达到{new_mark}次，获得{reward}数据碎片里程碑奖励",
                f"【dark】统计模块提示：你累计完成的{label}已经到了 "
                f"<font color='#4169E1'>{new_mark}</font> 次。"
                f"坚持这种事本身就比结果稀有。奖励 <font color='#FFD700'>{reward} 数据碎片</font>。")

    def build_plan_text(self, d=None, for_ai=True):
        """
        把某一天的真实日程/打卡拼成一段文字。
        这是"防瞎编"的关键：直接把真实数据喂给模型，它就没有编造的空间了。
        """
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

    def speak_today_plan(self, d=None):
        """让 Giegisa 基于真实数据说说这一天的安排"""
        d = d or date.today()
        data = self.build_plan_text(d)
        items = schedules_of_day(self.config, d)
        if not items and not (d == date.today() and active_checkins(self.config)):
            self.inject_system_event(
                f"系统：用户查看了 {d.strftime('%m月%d日')} 的安排，当天没有任何日程",
                f"【normal】{d.strftime('%m月%d日')}。你什么都没安排。是打算放空，还是单纯忘了记？")
            return
        self.send_msg(
            f"【系统后台强制指令：以下是用户的真实日程数据，请严格按照这些内容播报，"
            f"绝对不许添加、删减或编造任何条目。用你的口吻简短复述并给一句评价（60字以内）。\n{data}】",
            hidden=True)

    def daily_rollover(self):
        """
        跨天处理（每天 0 点自动触发一次）：
        - 把所有日程的"今天提醒过了"标记清零，这样每天到点都会重新提醒
        - 刷新已经打开的日历/打卡面板
        """
        for s in self.config.get("schedules", []):
            if isinstance(s, dict) and s.get("notified"):
                s["notified"] = False
        self._checkin_notified = set()
        save_config(self.config)
        self.refresh_dialogs("dlg_MiniCalendarDialog", "dlg_CheckinDialog",
                             "dlg_StatsDialog", "dlg_ScheduleDialog")

    def check_clipboard(self):
        if not self.config.get("clipboard_enabled", True): return
        text = QApplication.clipboard().text()
        # 监测内容变化并显示按钮
        if text and text != self.last_clipboard and len(text) > 10:
            self.last_clipboard = text
            self.analyze_btn.show() # 显示按钮
            self.analyze_btn.setText(f"✨ 识别: {text[:8]}...") # 显示截断内容
            # 5秒后自动隐藏按钮，防止挡住桌宠
            QTimer.singleShot(5000, self.analyze_btn.hide)
            
    def process_clipboard(self):
        text = self.last_clipboard
        self.analyze_btn.hide()
        self.send_msg(f"【系统后台强制指令：请结合你的人物设定，中立地对这段剪贴板内容发表你的见解和人性化态度：{text}】", hidden=True)

    def check_media_status(self):
        # 【新增】：初始化深度记忆锁（记录已经评价过的媒体）
        if not hasattr(self, 'commented_media_title'):
            self.commented_media_title = ""

        # 专注模式中，媒体类窗口应只触发"摸鱼拦截"，不再同时触发普通媒体点评，
        # 否则会出现一边训斥摸鱼、一边兴致勃勃点评视频的冲突回复。
        if self.is_focus_mode:
            self.last_media_title = ""
            self.media_start_time = 0
            return
            
        # 开关判断
        if not self.config.get("media_enabled", True): 
            self.last_media_title = ""
            self.media_start_time = 0
            self.commented_media_title = "" # 关掉开关时也清空深度记忆
            return
    
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd: return
        title_len = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if title_len == 0: return 
        
        buf = ctypes.create_unicode_buffer(title_len + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, title_len + 1)
        title = buf.value
        
        if not title: return
        
        media_list = ["网易云", "qq音乐", "酷狗音乐", "alger", "folia", "爱奇艺", "抖音", "快手", "小红书", "bilibili", "acfun", "youtube", "music", "video", "anime", "player", "播放", "音乐", "动画", "视频"]
        
        if any(keyword.lower() in title.lower() for keyword in media_list):
            if title != self.last_media_title:
                # 标题变动，锁定当前曲目，开始1秒计时
                self.last_media_title = title
                self.media_start_time = time.time()
            elif self.media_start_time > 0 and (time.time() - self.media_start_time >= 1):
                # 满1秒后，检查是否已经对"这个特定标题"发表过见解
                self.media_start_time = 0 # 无论发不发，先锁住计时器
                
                if title != self.commented_media_title:
                    # 只有当标题不等于已评价过的标题时，才发送指令
                    self.commented_media_title = title # 把它加入已评价备忘录
                    self.send_msg(f"【系统后台强制指令：用户正在播放：{title}。请结合你的人物设定以及精准检索到的深度延伸信息（作者/风格/相关文化/其他等），过滤无意义噪声，关注核心曲目或视频标题，中立地发表一下你的简短评价和人性化态度。】", hidden=True)
        else:
            # 【修复核心】：切出媒体软件时，只重置当前状态，绝对不碰 commented_media_title！
            # 这样就算你中间切出去聊微信，再切回同一个视频，Gisa 也记得自己已经吐槽过了，绝不废话。
            self.last_media_title = ""
            self.media_start_time = 0

    def handle_api_lag(self, elapsed):
        self.change_mood(-5)
        self.inject_system_event("系统：检测到API响应卡顿", f"【angry】网络传输延迟达到了 {elapsed:.1f} 秒... 这种低效的数据链路让我非常烦躁。")

    def resizeEvent(self, event):
        if event.oldSize().height() > 0:
            self.move(self.x(), self.y() - (event.size().height() - event.oldSize().height()))
        super().resizeEvent(event)

    def check_daily_signin(self):
        today = str(date.today())
        if self.config.get("last_sign_in") != today:
            self.config["coins"] += 50
            self.config["last_sign_in"] = today
            save_config(self.config)
            QTimer.singleShot(2000, lambda: self.inject_system_event("系统：用户每日签到", "【normal】启动验证完成。今天按时上线了，奖励 50 数据碎片。好好干活。"))

    def init_input_counter(self):
        # 尝试用 pynput 做全局计数(统计整台电脑的点击/敲击，像 bongo cat)。
        # 没装 pynput 也绝不会崩：会自动退回"只统计点在桌宠身上的点击"。
        try:
            from pynput import mouse as _pmouse, keyboard as _pkeyboard

            def _on_click(x, y, button, pressed):
                if pressed:
                    self.session_clicks += 1

            def _on_press(key):
                self.session_keys += 1

            self._mouse_listener = _pmouse.Listener(on_click=_on_click)
            self._kb_listener = _pkeyboard.Listener(on_press=_on_press)
            self._mouse_listener.daemon = True
            self._kb_listener.daemon = True
            self._mouse_listener.start()
            self._kb_listener.start()
            self.global_input_hook_active = True
        except Exception:
            # 没有 pynput(或系统不允许全局钩子)时，静默退回本地计数，不影响其它功能
            self.global_input_hook_active = False

    def flush_input_counter(self, force=False):
        # 把"本次新增"的点击/敲击累加进长期总数并存盘(增量方式，避免重复计数)。
        try:
            d_click = self.session_clicks - self._flushed_clicks
            d_key = self.session_keys - self._flushed_keys
            if d_click > 0 or d_key > 0:
                self.config["total_clicks"] = self.config.get("total_clicks", 0) + max(0, d_click)
                self.config["total_keys"] = self.config.get("total_keys", 0) + max(0, d_key)
                self._flushed_clicks = self.session_clicks
                self._flushed_keys = self.session_keys
                save_config(self.config, force=force)
        except Exception:
            pass

    def flush_before_exit(self):
        """退出前把计数和其它节流中的改动一次性安全落盘。"""
        if self._shutting_down:
            return
        self._shutting_down = True
        self.close_all_dialogs()
        # pynput 的监听线程若留到 Python/Qt 清理阶段，Windows 下可能异常退出。
        for name in ("_mouse_listener", "_kb_listener"):
            listener = getattr(self, name, None)
            if listener is None:
                continue
            try:
                listener.stop()
                listener.join(0.5)
            except Exception:
                pass
            setattr(self, name, None)
        self.global_input_hook_active = False
        self.flush_input_counter(force=True)
        flush_config_if_dirty(self.config)
        try:
            self.tray_icon.hide()
        except Exception:
            pass

    def init_images(self):
        self.pics = {}
        outfit = self.config.get("current_outfit", "default")
        img_list = ["normal1", "normal2", "zhayan1", "zhayan2", "biyan", "shy", "shyspeak", "angry", "angryspeak", "angrysmile", "angrysmilespeak"]
        
        for name in img_list:
            prefixed = os.path.join(PIC_DIR, f"{outfit}_{name}.png")
            std = os.path.join(PIC_DIR, f"{name}.png")
            if outfit != "default" and os.path.exists(prefixed):
                self.pics[name] = QPixmap(prefixed)
            elif os.path.exists(std):
                self.pics[name] = QPixmap(std)
            else:
                fb = QPixmap(200, 200)
                fb.fill(Qt.GlobalColor.gray)
                self.pics[name] = fb

    def init_ui(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 使用清除布局的方式防止重复堆叠
        # 注意：原来这里写的是 self.layout = QVBoxLayout(self)，把 QWidget 自带的 layout() 方法
        # 覆盖成了一个对象。一旦 init_ui 被第二次调用，self.layout() 就会报"对象不可调用"。
        # 改名成 main_layout，彻底避开这个坑。
        if self.layout():
            QWidget().setLayout(self.layout())
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        
        # 1. 气泡层
        self.chat_bubble = QLabel("")
        self.chat_bubble.setWordWrap(True)
        self.chat_bubble.setTextFormat(Qt.TextFormat.RichText)
        self.chat_bubble.setMinimumHeight(30)
        self.chat_bubble.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.MinimumExpanding)
        self.apply_bubble_style()
        self.chat_bubble.hide()
        self.main_layout.addWidget(self.chat_bubble)
        
        # 2. 剪贴板识别按钮 (头顶)
        self.analyze_btn = QPushButton("✨ 识别剪贴板", self)
        self.analyze_btn.setStyleSheet("background-color: #2196F3; color: white; border-radius: 5px;")
        self.analyze_btn.hide()
        self.analyze_btn.clicked.connect(self.process_clipboard)
        self.main_layout.addWidget(self.analyze_btn)
        
        # 3. 桌宠图像
        self.pet_label = QLabel()
        self.pet_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.update_idle_face()
        self.main_layout.addWidget(self.pet_label)
        
        # 4. 图片附件提示条（默认隐藏，粘贴图片后出现）
        self.image_hint = QPushButton("🖼️ 已附加图片，输入文字后回车发送 · 点此取消")
        self.image_hint.setStyleSheet("background-color: #7E57C2; color: white; border-radius: 5px; font-family: 'Microsoft YaHei'; font-size: 12px; padding: 3px;")
        self.image_hint.hide()
        self.image_hint.clicked.connect(self.clear_pending_image)
        self.main_layout.addWidget(self.image_hint)

        # 5. 输入框
        self.input_box = ChatInputBox()
        self.input_box.returnPressed.connect(self.send_msg)
        self.input_box.image_pasted.connect(self.on_image_pasted)
        self.input_box.setVisible(self.config.get("show_input_box", True))
        self.main_layout.addWidget(self.input_box)
        
        # QVBoxLayout(self) 已经自动安装到窗口上，不需要再次 setLayout。
        
        # 5. 系统托盘
        if not hasattr(self, 'tray_icon'):
            self.tray_icon = QSystemTrayIcon(self)
            tray_image_path = os.path.join(PIC_DIR, "giegisa.png")
            if os.path.exists(tray_image_path):
                self.tray_icon.setIcon(QIcon(tray_image_path))
            else:
                self.tray_icon.setIcon(QIcon(self.pics.get("normal1", QPixmap(32, 32))))
            self.tray_icon.setToolTip("Giegisa - 跨位面连线终端")
            self.tray_icon.activated.connect(self.tray_activated)
            self.tray_icon.show()
        
        sg = QApplication.primaryScreen().availableGeometry()
        self.move(sg.width() - 400, sg.height() - 400)
        
        

    def apply_bubble_style(self):
        self.chat_bubble.setMaximumWidth(self.config["bubble_width"])
        self.chat_bubble.setStyleSheet(f"""
            QLabel {{
                background-color: {self.config['bubble_bg']};
                border-radius: 10px;
                border: 2px solid {self.config['bubble_border']};
                padding: 10px;
                color: {self.config.get('bubble_font_color', '#333333')};
                font-family: 'Microsoft YaHei';
                font-size: 14px;
                font-weight: bold;
            }}
        """)

    def init_timers(self):
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.blink_anim)
        self.blink_timer.start(random.randint(2000, 5000))
        
        self.speak_timer = QTimer(self)
        self.speak_timer.timeout.connect(self.speak_anim)
        
        self.type_timer = QTimer(self)
        self.type_timer.timeout.connect(self.typewriter_effect)
        
        self.end_blink_timer = QTimer(self)
        self.end_blink_timer.timeout.connect(self.toggle_end_blink)
        self.end_blink_state = False

        self.core_clock_timer = QTimer(self)
        self.core_clock_timer.timeout.connect(self.core_clock_tick)
        self.core_clock_timer.start(1000)
        
        self.clipboard_timer = QTimer(self)
        self.clipboard_timer.timeout.connect(self.check_clipboard)
        self.clipboard_timer.start(2000) # 2秒检测一次剪贴板
        self.last_clipboard = ""

        self.media_timer = QTimer(self)
        self.media_timer.timeout.connect(self.check_media_status)
        self.media_timer.start(10000) # 10秒检测一次媒体标题
        self.last_media_title = ""
        self.media_start_time = 0 # 【新增】记录该媒体开始播放的时间点
        
        

    def core_clock_tick(self):
        now = datetime.now()
        if now.second in (0, 30):
            self.flush_input_counter()  # 每半分钟把鼠标/键盘计数存盘一次(增量，开销极小)
        
        if random.randint(1, 100) == 1: 
            if self.session_mood > 50:
                self.change_mood(-1)
            elif self.session_mood < 50:
                self.change_mood(1)
            if not self.is_speaking:
                self.update_idle_face()
            
        if now.minute == 0 and now.second == 0:
            if not self.hourly_triggered:
                self.hourly_triggered = True
                if self.config.get("hourly_chime_enabled", True):
                    current_time_str = now.strftime("%H:00")
                    self.send_msg(f"【系统后台强制指令：当前本地时间是 {current_time_str}。请用符合性格的方式简短报时提醒。】", hidden=True)
        elif now.second > 1:
            self.hourly_triggered = False
            
        # ---- 跨天翻篇：每天 0 点重置提醒标记、刷新面板 ----
        today = now.date()
        if getattr(self, "_last_seen_date", None) != today:
            if getattr(self, "_last_seen_date", None) is not None:
                self.daily_rollover()
            self._last_seen_date = today

        now_str = now.strftime("%H:%M")
        # 首先检查全局提醒总开关是否开启
        if self.config.get("schedule_reminder_enabled", True):
            need_save = False
            for sched in self.config.get("schedules", []):
                if not isinstance(sched, dict):
                    continue
                today_key = today.strftime("%Y-%m-%d")
                # 同时满足：时间匹配、今天该发生、今天没提醒过、未完成、且单项铃声开启。
                # 使用具体日期记录通知状态，避免程序隔天重启后 notified=True 导致永远不再提醒。
                if (str(sched.get("time")) == now_str
                        and sched.get("last_notified_date") != today_key
                        and sched.get("status") == "pending"
                        and sched.get("alarm_on", True)
                        and sched_occurs_on(sched, today)
                        and not sched_done_on(sched, today)):
                    sched["notified"] = True  # 保留旧字段，方便旧版继续读取
                    sched["last_notified_date"] = today_key
                    need_save = True
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    self.raise_()  # 只在自身层级内抬升，不再强行抢占系统置顶，避免和其它置顶软件互相打架(提醒弹窗本身是置顶的，仍看得到)
                    self.queue_reminder("schedule", sched.get("task", ""), sched.get("note", ""))
            if need_save:
                save_config(self.config)

        # ---- 打卡提醒：到点还没打卡就提醒一次（同一时间点每天只提醒一次）----
        if self.config.get("checkin_reminder_enabled", True):
            if not hasattr(self, "_checkin_notified"):
                self._checkin_notified = set()
            for c in active_checkins(self.config):
                if not c.get("enabled", True):
                    continue
                if now_str not in (c.get("remind_times") or []):
                    continue
                key = (c.get("id"), now_str)
                if key in self._checkin_notified:
                    continue
                self._checkin_notified.add(key)
                if not checkin_done_on(c, today):
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    self.queue_reminder("checkin", c)

        # ---- 电子书每日阅读提醒：阅读器未打开时也能由桌宠提醒一次 ----
        ebook_settings = self.config.get("ebook_settings", {})
        if (ebook_settings.get("daily_reminder_enabled", False)
                and now_str == ebook_settings.get("daily_reminder_time", "20:00")
                and self.config.get("ebook_last_reminder_date") != str(today)):
            daily = self.config.get("ebook_reading_daily", {}).get(str(today), {})
            goal_seconds = int(ebook_settings.get("daily_goal_minutes", 5)) * 60
            if int(daily.get("seconds", 0)) < goal_seconds:
                self.config["ebook_last_reminder_date"] = str(today)
                save_config(self.config, force=False)
                self.inject_system_event(
                    "系统：到达每日电子书阅读提醒时间",
                    f"【normal】今天的阅读目标还没完成。至少打开静默阅读舱读 "
                    f"<font color='#4169E1'>{ebook_settings.get('daily_goal_minutes', 5)} 分钟</font>。")

        # ---- 把攒下的"非关键改动"统一落盘，避免频繁写磁盘 ----
        if now.second % 5 == 0:
            flush_config_if_dirty(self.config)

        if self.is_focus_mode:
            if self.focus_type == "stopwatch":
                self.focus_seconds += 1
                if self.focus_seconds % 2 == 0:
                    self.check_distraction()
            else:
                self.focus_seconds -= 1
                if getattr(self, "focus_state", "work") == "work" and self.focus_seconds % 2 == 0:
                    self.check_distraction()
                
            if hasattr(self, "focus_overlay") and self.focus_overlay and self.focus_overlay.isVisible():
                self.focus_overlay.update_display()

            if self.focus_type != "stopwatch" and self.focus_seconds <= 0:
                if self.focus_type == "normal":
                    self.is_focus_mode = False
                    reward = random.randint(20, 50)
                    self.config["coins"] += reward
                    save_config(self.config)
                    self.change_mood(10)
                    self.inject_system_event(f"系统：用户完成了普通倒计时专注并获得{reward}数据碎片", f"【shy】...时间到了。勉强算你专注过了。赏你 <font color='#FFD700'>{reward} 个数据碎片</font> 吧。")
                    if self.focus_overlay:
                        self.focus_overlay.hide()
                    
                elif self.focus_type == "pomodoro":
                    if self.focus_state == "work":
                        self.focus_sets_done += 1
                        reward = random.randint(15, 30)
                        self.config["coins"] += reward
                        save_config(self.config)
                        self.change_mood(5)
                        self.inject_system_event(f"系统：用户完成了第{self.focus_sets_done}个番茄钟并获得{reward}数据碎片", f"【normal】第{self.focus_sets_done}组专注完成。拿好这 <font color='#FFD700'>{reward} 数据碎片</font>。现在允许你稍微放松一下。")
                        
                        if self.focus_sets_done >= self.focus_sets_total:
                            self.is_focus_mode = False
                            self.inject_system_event("系统：番茄钟全部循环完成", "【shy】所有循环全做完了？哼，还算有点毅力。休息去吧。")
                            if self.focus_overlay:
                                self.focus_overlay.hide()
                        else:
                            self.focus_state = "rest"
                            self.focus_seconds = self.focus_rest_duration * 60
                            self.focus_start_dt = datetime.now()
                            self.focus_end_dt = self.focus_start_dt + timedelta(seconds=self.focus_seconds)
                    else:
                        self.focus_state = "work"
                        self.focus_seconds = self.focus_work_duration * 60
                        self.focus_start_dt = datetime.now()
                        self.focus_end_dt = self.focus_start_dt + timedelta(seconds=self.focus_seconds)
                        self.inject_system_event("系统：番茄钟休息结束", "【dark】休息时间到此为止。立刻回来继续专注！")
                        
        self.idle_seconds += 1
        self.event_seconds += 1
        self.note_seconds += 1
        
        if self.config.get("idle_chat_enabled", True):
            target_idle = self.config.get("idle_chat_interval_min", 20) * 60
            if self.idle_seconds >= target_idle:
                self.idle_seconds = 0
                self.idle_thread = IdleChatThread(self.config)
                self.idle_thread.result_ready.connect(self.on_idle_chat_fetched)
                self.idle_thread.start()
                
        if self.config.get("event_enabled", True):
            target_event = self.config.get("event_interval_min", 60) * 60
            if self.event_seconds >= target_event:
                self.event_seconds = 0
                self.event_thread = RandomEventThread(self.config)
                self.event_thread.result_ready.connect(self.on_random_event_fetched)
                self.event_thread.start()
                
        if self.config.get("read_notes_enabled", True):
            target_note = self.config.get("read_notes_interval_min", 30) * 60
            if self.note_seconds >= target_note:
                self.note_seconds = 0
                read_folder = self.config.get("read_notes_folder", "所有便签")
                active_notes = []
                for n in self.config.get("notes", []):
                    if n.get("status") == "active":
                        if read_folder == "所有便签" or n.get("folder", "默认便签") == read_folder:
                            active_notes.append(n)
                            
                if active_notes:
                    note = random.choice(active_notes)
                    self.inject_system_event("系统：Giegisa随机翻阅了便签", f"【normal】随手翻到了你留的一笔便签：「{note['text']}」。最好别忘了它。")

    def check_distraction(self):
        if not self.config.get("distraction_intercept_enabled", True):
            return
            
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        window_title = buf.value.lower()
        
        for kw, is_enabled in self.config.get("distraction_keywords", {}).items():
            if is_enabled and kw.lower() in window_title:
                self.change_mood(-15)
                self.shake_window()
                winsound.MessageBeep(winsound.MB_ICONHAND)
                self.inject_system_event("系统：检测到用户在专注期间摸鱼", "【dark】又在摸鱼？别以为我没看见你切到了违禁软件。立刻关掉，回去专注！")
                break

    def shake_window(self):
        """
        抖动动画。
        原实现用 time.sleep + processEvents 阻塞主线程约 0.24 秒，期间界面假死，
        而且 processEvents 会重入事件循环，可能引发难以复现的怪问题。
        改成定时器驱动，全程不阻塞。
        """
        if getattr(self, "_shake_timer", None) and self._shake_timer.isActive():
            return
        self._shake_origin = self.pos()
        self._shake_left = 6
        self._shake_timer = QTimer(self)

        def _step():
            if self._shake_left <= 0:
                self._shake_timer.stop()
                self.move(self._shake_origin)
                return
            offset = 10 if self._shake_left % 2 == 0 else -10
            self.move(self._shake_origin + QPoint(offset, 0))
            self._shake_left -= 1

        self._shake_timer.timeout.connect(_step)
        self._shake_timer.start(40)

    def start_focus_mode(self, cfg):
        self.is_focus_mode = True
        self.focus_type = cfg["type"]
        self.focus_start_dt = datetime.now()

        if self.focus_type == "normal":
            self.focus_seconds = cfg["minutes"] * 60
            self.focus_total_seconds = self.focus_seconds
            self.focus_end_dt = self.focus_start_dt + timedelta(seconds=self.focus_seconds)
            self.inject_system_event(f"系统：设定了{cfg['minutes']}分钟倒计时专注", "【normal】倒计时协议已建立。别想在我眼皮子底下偷懒。")
        elif self.focus_type == "stopwatch":
            self.focus_seconds = 0
            self.focus_end_dt = None
            self.inject_system_event("系统：启动了无限正计时专注", "【dark】正计时协议已启动。时间将不断累积，让我看看你能坚持多久。")
        else:
            self.focus_work_duration = cfg["work"]
            self.focus_rest_duration = cfg["rest"]
            self.focus_sets_total = cfg["sets"]
            self.focus_sets_done = 0
            self.focus_state = "work"
            self.focus_seconds = self.focus_work_duration * 60
            self.focus_end_dt = self.focus_start_dt + timedelta(seconds=self.focus_seconds)
            self.inject_system_event(f"系统：设定了{cfg['sets']}组番茄钟", f"【dark】番茄钟协议生效，共 {cfg['sets']} 组循环。在彻底结束前不准切出工作窗口。")

        if not hasattr(self, "focus_overlay") or self.focus_overlay is None:
            self.focus_overlay = FocusOverlay(self)
            
        is_top = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if is_top:
            self.focus_overlay.setWindowFlags(self.focus_overlay.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.focus_overlay.setWindowFlags(self.focus_overlay.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
            
        self.focus_overlay.move(self.x() - 150, self.y() - 50)
        self.focus_overlay.show()
        self.focus_overlay.update_display()

    def send_custom_ai_query(self, text):
        """用于系统小应用（日历、专注、随机剧场等）调用 AI 通信，不漏出提示词"""
        self.show_bubble("【normal】Giegisa 正在查看你的日程安排...")
        # 💡 痛点修复：复用现有的底层通信通道，完美兼容当前的 AI 架构
        self.send_msg(f"【系统后台强制指令：{text}】", hidden=True)

    def stop_focus_manually(self):
        self.is_focus_mode = False
        if hasattr(self, "focus_overlay") and self.focus_overlay:
            self.focus_overlay.hide()
            
        if self.focus_type == "stopwatch":
            mins = self.focus_seconds // 60
        elif self.focus_type == "normal":
            mins = (self.focus_total_seconds - self.focus_seconds) // 60
        else: 
            mins = self.focus_sets_done * self.focus_work_duration
            
        reward = mins * 1
        self.config["coins"] += reward
        save_config(self.config)
        self.inject_system_event(f"系统：用户主动终止了专注，时长为 {mins} 分钟", f"【normal】专注终止了。算你挣扎了 {mins} 分钟，勉强给你结算 {reward} 数据碎片。")

    def roll_dice_d100(self):
        num = random.randint(1, 100)
        self.inject_system_event("系统：用户进行了一次 d100 检定", f"【normal】检定结果为：<font color='#4169E1'>{num}</font>。")

    def roll_daily_luck(self):
        luck_list = [
            ("大吉", "【shy】...看来你今天运气不错。去买彩票吧。"),
            ("中吉", "【normal】运势偏上。稳扎稳打就行。"),
            ("小吉", "【normal】小有运气。别太得意忘形。"),
            ("平", "【normal】毫无波澜的一天。这就是日常。"),
            ("小凶", "【angry】运势低迷。走路看着点脚下。"),
            ("大凶", "【dark】...呵，你今天最好乖乖待在家里。")
        ]
        luck, text = random.choice(luck_list)
        self.inject_system_event("系统：用户进行了今日运势检定", f"{text} (运势检定：<font color='#E53935'>{luck}</font>)")

    def draw_tarot(self):
        tarot_cards = [
            "愚者", "魔术师", "女祭司", "女皇", "皇帝", "教皇", "恋人", "战车", 
            "力量", "隐士", "命运之轮", "正义", "倒吊人", "死神", "节制", "恶魔", 
            "高塔", "星星", "月亮", "太阳", "审判", "世界"
        ]
        card = random.choice(tarot_cards)
        position = random.choice(["正位", "逆位"])
        color = "#4CAF50" if position == "正位" else "#E53935"
        self.inject_system_event("系统：用户进行了一次塔罗牌占卜", f"【dark】命运的切片已落定。你抽到了：<font color='{color}'>{card} - {position}</font>。至于这意味着什么，你自己去领悟。")

    def update_image(self, img_key):
        if img_key in self.pics:
            scaled_pixmap = self.pics[img_key].scaled(
                self.scale_size, self.scale_size, 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.pet_label.setPixmap(scaled_pixmap)
            
    def change_mood(self, delta):
        self.session_mood = max(0.0, min(100.0, self.session_mood + delta))
        self.total_mood = max(0.0, min(100.0, self.total_mood + delta * 0.2))
        self.config["total_mood"] = self.total_mood
        save_config(self.config, force=False)
        self.update_idle_face()
        
        if hasattr(self, 'dlg_MoodDialog') and getattr(self, 'dlg_MoodDialog'):
            try:
                self.dlg_MoodDialog.update_display()
            except RuntimeError:
                pass
                
    def update_idle_face(self):
        if self.session_mood < 30: 
            face = "angry"
        elif self.total_mood >= 76 and self.config.get("allow_blush", False): 
            face = "shy"
        else:
            face = "normal1"
        self.update_image(face)

    def blink_anim(self):
        if self.is_speaking: return 
        self.update_image("zhayan1")
        QTimer.singleShot(50, lambda: self.update_image("zhayan2"))
        QTimer.singleShot(150, self.update_idle_face)
        self.blink_timer.setInterval(random.randint(2000, 6000))

    def speak_anim(self):
        if not self.is_speaking:
            self.speak_timer.stop()
            self.update_idle_face()
            return
            
        speak_map = {
            "normal": ("normal1", "normal2"), 
            "shy": ("shy", "shyspeak"),
            "angry": ("angry", "angryspeak"), 
            "dark": ("angrysmile", "angrysmilespeak")
        }
        frames = speak_map.get(self.current_emotion, ("normal1", "normal2"))
        
        if not hasattr(self, "speak_toggle"):
            self.speak_toggle = False
            
        self.speak_toggle = not self.speak_toggle
        self.update_image(frames[1] if self.speak_toggle else frames[0])

    def on_image_pasted(self):
        """输入框里粘贴了图片后，显示提示条"""
        self.image_hint.show()
        self.adjustSize()

    def clear_pending_image(self):
        """取消已附加的图片"""
        self.input_box.clear_pending_image()
        self.image_hint.hide()
        self.adjustSize()

    def send_msg(self, text_override=None, hidden=False):
        self.idle_seconds = 0
        msg = text_override if text_override else self.input_box.toPlainText().strip()

        # 取出待发送的图片（只有手动输入这一路才带图，后台隐藏指令不带图）
        image_b64 = None
        image_mime = "image/png"
        if not hidden:
            image_b64 = getattr(self.input_box, "pending_image_b64", None)
            image_mime = getattr(self.input_box, "pending_image_mime", "image/png")

        # 文字和图片都为空才算空消息
        if not msg and not image_b64:
            return

        # 上一条还在等回复时，避免同时发起多条请求造成线程冲突/卡顿
        if self.chat_thread.isRunning():
            if not hidden:
                self.show_bubble("【normal】上一条还在处理，请稍候。")
            return

        # 如果只贴了图没打字，给一句默认引导语
        if not msg and image_b64:
            msg = "请结合你的人设，看看这张图片并作出回应。"

        if not hidden:
            self.input_box.clear()
            self.clear_pending_image()   # 图片发出后清空附件与提示条
            self.show_bubble("...") 
            self.update_image("biyan") 
            
        pos_words = ["喜欢", "爱", "谢谢", "好棒", "贴贴", "摸摸", "乖", "厉害", "赞", "可爱"]
        neg_words = ["傻", "笨", "滚", "去死", "闭嘴", "垃圾", "讨厌", "废", "烦", "慢"]
        
        if any(w in msg for w in pos_words):
            self.change_mood(2)
        if any(w in msg for w in neg_words):
            self.change_mood(-5)

        if self.session_mood > 75: 
            mood_state = "【情绪状态：Happy (极佳)】此刻心情很好。语气允许微傲娇、放松，甚至可以稍微对用户展现出一丝关心。"
        elif self.session_mood < 30: 
            mood_state = "【情绪状态：Sad/Angry (烦躁)】刚刚遭遇卡顿或负面事件，极其不爽。展现出冷酷、不耐烦的S属性，回复必须【极端简短、冰冷】。"
        else: 
            mood_state = "【情绪状态：Normal (平常)】平稳运行中。保持高冷、冷静、可靠的女王属性常规姿态。"
        
        prof = self.config.get("user_profile", {})
        prof_info = ""
        if prof.get("nickname") or prof.get("relationship"):
            prof_info = f"\n[后台强制潜意识：当前与你对话的用户信息 -> 称呼：{prof.get('call_me','默认')}，昵称：{prof.get('nickname','')}，生日：{prof.get('birthday','')}，关系设定：{prof.get('relationship','')}]"

        mood_prompt = f"\n[后台状态干预：当前你的沟通情绪值是{int(self.session_mood)}/100，总好感度{int(self.total_mood)}/100，状态为：{mood_state}。请绝对遵循此状态输出回复。]{prof_info}"

        # ===== 防瞎编：把"今天的真实日程/打卡"作为事实喂给模型 =====
        # 模型之所以会编造日程，是因为它压根看不到你的数据。给了真实数据，它就没得编。
        if self.config.get("schedule_context_enabled", True):
            try:
                snapshot = self.build_plan_text()
                mood_prompt += ("\n[事实数据·当前时间与用户日程（这是唯一可信来源，"
                                "回答任何与日程/待办/打卡相关的问题时必须以此为准，"
                                "此处没有的就是没有，绝对不许编造）："
                                f"现在是 {datetime.now().strftime('%Y-%m-%d %H:%M')}。{snapshot}]")
            except Exception:
                pass
        
        self.chat_thread.send_message(msg, mood_prompt, image_b64=image_b64, image_mime=image_mime)

    def on_idle_chat_fetched(self, text):
        self.inject_system_event("系统：Giegisa发起了闲聊", text)

    def on_random_event_fetched(self, data):
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
        dlg = RandomEventDialog(self, data)
        dlg.show()

    def inject_system_event(self, user_action, ai_response):
        clean_response = sanitize_bubble_text(ai_response)
        now_ts = time.time()
        self.chat_thread.history.append({"role": "user", "content": f"（{user_action}）", "timestamp": now_ts})
        self.chat_thread.history.append({"role": "assistant", "content": clean_response, "timestamp": now_ts})
        self.chat_thread.save_history()
        self.handle_api_reply(ai_response)

    def handle_api_reply(self, reply_text, type_interval=None):
        reply_text = str(reply_text or "")
        if hasattr(self, 'dlg_HistoryDialog') and getattr(self, 'dlg_HistoryDialog'):
            try:
                self.dlg_HistoryDialog.refresh_list()
            except RuntimeError:
                pass
                
        # 只拦截模型明显在复读后台指令的异常回复。
        # 正常回答中偶然提到这几个字时，不应该把整条回复吞掉。
        if reply_text.strip().startswith(
                ("【系统后台强制指令", "[系统后台强制指令", "系统后台强制指令")):
            self.chat_bubble.hide()
            return

        if self.is_typing:
            queued = (str(reply_text), type_interval)
            if not self._bubble_queue or self._bubble_queue[-1] != queued:
                self._bubble_queue.append(queued)
                self._bubble_queue = self._bubble_queue[-8:]
            return
        hold_left = self._bubble_hold_until - time.time()
        if hold_left > 0 and self.chat_bubble.isVisible():
            queued = (reply_text, type_interval)
            if not self._bubble_queue or self._bubble_queue[-1] != queued:
                self._bubble_queue.append(queued)
                self._bubble_queue = self._bubble_queue[-8:]
            self._schedule_next_bubble(int(hold_left * 1000) + 20)
            return
        
        self.current_emotion = "normal"

        match = _EMOTION_TOKEN_RE.search(reply_text)
        if match:
            emo = match.group(1).lower()
            if emo in ["shy", "angry", "dark"]:
                self.current_emotion = emo
        reply_text = sanitize_bubble_text(reply_text)
     
        # --- 解析 Markdown 图片链接 ---
        img_urls = re.findall(r'!\[.*?\]\((.*?)\)', reply_text)
        # 从文字气泡中把这串杂乱的链接抹掉
        reply_text = re.sub(r'!\[.*?\]\(.*?\)', '', reply_text).strip()
        
        # 为每张图片生成独立的悬浮气泡
        for url in img_urls:
            self.show_image_bubble(url)
            
        self.full_text = reply_text
        self._pending_type_interval = type_interval
        if self.full_text:
            self.play_text()
        else:
            self.chat_bubble.hide() # 如果这条回复纯粹只是发图，直接隐藏文字气泡

    # 新增独立唤起气泡的方法：
    def show_image_bubble(self, url):
        img_bubble = ImageBubble(self)
        # 随机错开坐标，防多张图完全叠在一起
        offset_x = random.randint(-50, 50)
        offset_y = random.randint(-50, 50)
        img_bubble.move(self.x() - 150 + offset_x, self.y() - 150 + offset_y)
        img_bubble.show()
        
        thread = ImageFetchThread(url)
        # 挂载在主类防止被内存回收机制闪退清理
        if not hasattr(self, 'img_threads'):
            self.img_threads = []
        self.img_threads.append((thread, img_bubble))
        thread.finished.connect(img_bubble.load_image)
        # 下载结束后把这条记录清掉，避免长时间使用时列表只增不减（内存泄漏）
        thread.finished.connect(lambda *_: self._cleanup_img_thread(thread, img_bubble))
        thread.error.connect(lambda *_: self._cleanup_img_thread(thread, img_bubble))
        thread.start()

    def _cleanup_img_thread(self, thread, bubble):
        try:
            self.img_threads = [(t, b) for (t, b) in getattr(self, 'img_threads', []) if t is not thread]
        except Exception:
            pass

    def play_text(self):
        self.display_text = ""
        self.text_index = 0
        self.is_typing = True
        self.can_skip = True
        self.is_speaking = True
        self.end_blink_timer.stop()
        
        self.chat_bubble.show()
        self.speak_timer.start(200)
        interval = self._pending_type_interval
        self._pending_type_interval = None
        self.type_timer.start(max(10, int(interval or 50)))

    def typewriter_effect(self):
        if self.text_index < len(self.full_text):
            if self.full_text[self.text_index] == '<':
                end_idx = self.full_text.find('>', self.text_index)
                if end_idx != -1:
                    self.display_text += self.full_text[self.text_index:end_idx+1]
                    self.text_index = end_idx + 1
                    return 
            self.display_text += self.full_text[self.text_index]
            self.chat_bubble.setText(self.display_text)
            # 外层 adjustSize 会连带更新气泡；不再为每个字重复做两次布局。
            self.adjustSize()
            self.text_index += 1
        else:
            self.finish_typing()

    def finish_typing(self):
        self.type_timer.stop()
        self.is_typing = False
        self.is_speaking = False
        self.end_blink_state = True
        self.toggle_end_blink() 
        self.end_blink_timer.start(500)
        self._bubble_hold_until = time.time() + 1.2
        if self._bubble_queue:
            self._schedule_next_bubble(1200)

    def _schedule_next_bubble(self, delay_ms):
        if self._bubble_dispatch_pending:
            return
        self._bubble_dispatch_pending = True
        QTimer.singleShot(max(0, delay_ms), self._play_next_bubble)

    def _play_next_bubble(self):
        self._bubble_dispatch_pending = False
        if self.is_typing or not self._bubble_queue:
            return
        hold_left = self._bubble_hold_until - time.time()
        if hold_left > 0 and self.chat_bubble.isVisible():
            self._schedule_next_bubble(int(hold_left * 1000) + 20)
            return
        text, interval = self._bubble_queue.pop(0)
        self.handle_api_reply(text, interval)

    def toggle_end_blink(self):
        self.end_blink_state = not self.end_blink_state
        indicator = " <font color='#888888'>▼</font>" if self.end_blink_state else " <font color='transparent'>▼</font>"
        self.chat_bubble.setText(self.display_text + indicator)

    def mouseReleaseEvent(self, event):
        self.idle_seconds = 0
        if event.button() == Qt.MouseButton.LeftButton:
            if self.is_typing and self.can_skip:
                self.display_text = self.full_text
                self.finish_typing()
                self.can_skip = False 
                self.chat_bubble.adjustSize()
                self.adjustSize()
                QTimer.singleShot(300, lambda: setattr(self, 'can_skip', True))
            elif not self.is_typing and self.chat_bubble.isVisible():
                self.end_blink_timer.stop()
                self.chat_bubble.hide()
                self._bubble_hold_until = 0.0
                self.adjustSize() 
                QTimer.singleShot(0, self._play_next_bubble)

    def mousePressEvent(self, event):
        self.idle_seconds = 0 
        if not getattr(self, "global_input_hook_active", False):
            self.session_clicks = getattr(self, "session_clicks", 0) + 1  # 未装 pynput 时的兜底计数
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_following = True
            self.mouse_drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if Qt.MouseButton.LeftButton and self.is_following:
            self.move(event.globalPosition().toPoint() - self.mouse_drag_pos)
            event.accept()

    def open_dialog(self, DialogClass, *args):
        suffix = "_" + str(args[0]) if args and isinstance(args[0], str) else ""
        dlg_name = f"dlg_{DialogClass.__name__}{suffix}"
        if not hasattr(self, dlg_name) or getattr(self, dlg_name) is None:
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
                new_dlg = DialogClass(self, *args)
                setattr(self, dlg_name, new_dlg)
                new_dlg.show()

    def close_all_dialogs(self):
        """提供一个始终可从托盘调用的解锁出口。"""
        self._alert_queue.clear()
        for attr, dlg in list(self.__dict__.items()):
            if not attr.startswith("dlg_") or dlg is None:
                continue
            try:
                dlg.close()
            except RuntimeError:
                self.__dict__[attr] = None
        if self._active_alert is not None:
            try:
                self._active_alert.close()
            except RuntimeError:
                self._active_alert = None

    def toggle_focus_overlay(self):
        if hasattr(self, "focus_overlay") and self.focus_overlay:
            if self.focus_overlay.isVisible():
                self.focus_overlay.hide()
            else:
                self.focus_overlay.show()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.Context):
            # 获取托盘图标的几何位置
            pos = self.tray_icon.geometry().center()
            self.show_context_menu(pos)

    def contextMenuEvent(self, event):
        self.show_context_menu(QCursor.pos())

    def _build_context_menu(self):
        """构建右键菜单（只执行一次，QActions 的 parent 均设为 menu 自身避免泄漏）。"""
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        # ---- 静态项 ----
        menu.addAction("🔌 登录为 Conveyor",
                       lambda: self.open_dialog(UserProfileDialog))
        menu.addAction("📝 随手记 (便签/灵感)",
                       lambda: self.open_dialog(QuickNoteDialog))
        menu.addAction("💖 查询好感度/当前心情",
                       lambda: self.open_dialog(MoodDialog))
        menu.addAction("⏱️ 强制专注协议 (计时/防摸鱼监控)",
                       lambda: self.open_dialog(FocusDialog))

        # 专注模式动态项 —— 用空 action 占位，show 时更新
        self._focus_stop_action = QAction("", menu)
        self._focus_stop_action.setVisible(False)
        self._focus_stop_action.triggered.connect(self.stop_focus_manually)
        self._focus_overlay_action = QAction("", menu)
        self._focus_overlay_action.setVisible(False)
        self._focus_overlay_action.triggered.connect(self.toggle_focus_overlay)
        menu.addAction(self._focus_stop_action)
        menu.addAction(self._focus_overlay_action)

        menu.addAction("📅 传达者日程系统 (提醒/待办)",
                       lambda: self.open_dialog(ScheduleDialog))

        cal_menu = QMenu("📅 时序日历 (月历/打卡/统计)", menu)
        cal_menu.addAction("🗓️ 迷你月历",
                           lambda: self.open_dialog(MiniCalendarDialog))
        cal_menu.addAction("📌 每日打卡",
                           lambda: self.open_dialog(CheckinDialog))
        cal_menu.addAction("📊 完成情况统计",
                           lambda: self.open_dialog(StatsDialog))
        cal_menu.addSeparator()
        cal_menu.addAction("💬 让 Gisa 说说今天的安排",
                           lambda: self.speak_today_plan())
        menu.addMenu(cal_menu)

        menu.addAction("📚 静默阅读舱 (书架/电子书)",
                       lambda: self.open_dialog(EbookShelfDialog))
        menu.addAction("🛒 数据交换商城 (买资源/知识/调取记录)",
                       lambda: self.open_dialog(StoreDialog))

        dice_menu = QMenu("🎲 命运检定 (掷骰/塔罗)", menu)
        dice_menu.addAction("🎲 基础检定 (d100)", self.roll_dice_d100)
        dice_menu.addAction("🎭 骰娘延伸 (今日运势)", self.roll_daily_luck)
        dice_menu.addAction("🃏 塔罗占卜 (单张抽取)", self.draw_tarot)
        menu.addMenu(dice_menu)

        menu.addSeparator()
        menu.addAction("🎨 气泡/文字/交互",
                       lambda: self.open_dialog(AppearanceDialog))
        menu.addAction("⚙️ 自动化设置 (小剧场/闲聊)",
                       lambda: self.open_dialog(AutoEventSettingsDialog))
        menu.addAction("📝 记忆档案 (历史监控与回溯)",
                       lambda: self.open_dialog(HistoryDialog))
        menu.addAction("⚙️ 核心数据与接口 (人设/API)",
                       lambda: self.open_dialog(ApiSettingsDialog))

        scale_menu = QMenu("🔍 调整机体大小", menu)
        for s in [150, 200, 300, 400]:
            scale_menu.addAction(
                f"{s}x{s} px",
                lambda checked=False, size=s: self.change_scale(size))
        menu.addMenu(scale_menu)

        menu.addAction("📌 切换置顶状态", self.toggle_top)
        menu.addAction("🔄 重置机体位置 (居中)", self.reset_position)
        menu.addAction("🧹 关闭所有面板", self.close_all_dialogs)
        menu.addSeparator()
        menu.addAction("❌ 切断连接 (退出)", QApplication.instance().quit)

        return menu

    def show_context_menu(self, event):
        try:
            if getattr(self, "_context_menu", None) is None:
                self._context_menu = self._build_context_menu()
            menu = self._context_menu

            # 专注模式动态项
            in_focus = self.is_focus_mode
            self._focus_stop_action.setText("🛑 提前终止/结算专注")
            self._focus_stop_action.setVisible(in_focus)
            self._focus_overlay_action.setText("🕒 显示/隐藏专注悬浮窗")
            self._focus_overlay_action.setVisible(in_focus)

            menu.exec(QCursor.pos())

        except Exception as e:
            self.show_bubble(f"【normal】视觉模块故障：{str(e)}。")

    def reset_position(self):
        screen_geo = QApplication.primaryScreen().availableGeometry()
        self.move(screen_geo.width() // 2 - self.width() // 2, screen_geo.height() // 2 - self.height() // 2)

    def change_scale(self, size):
        self.scale_size = size
        self.update_idle_face()

    def toggle_top(self):
        flags = self.windowFlags()
        if bool(flags & Qt.WindowType.WindowStaysOnTopHint):
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
            if hasattr(self, "focus_overlay") and self.focus_overlay:
                self.focus_overlay.setWindowFlags(self.focus_overlay.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
            if hasattr(self, "focus_overlay") and self.focus_overlay:
                self.focus_overlay.setWindowFlags(self.focus_overlay.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.show()
        if hasattr(self, "focus_overlay") and self.focus_overlay and self.focus_overlay.isVisible():
            self.focus_overlay.show()

    def show_bubble(self, text, type_interval=None):
        # 所有本地提示也走统一清洗、打字机与说话动画，避免情绪标签外露，
        # 并防止多条提示在同一气泡中互相覆盖。
        self.handle_api_reply(text, type_interval)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    install_ice_glass_theme(app, UI_BACKGROUND_FILE)
    pet = DesktopPet()
    pet.show()
    app.aboutToQuit.connect(pet.flush_before_exit)
    sys.exit(app.exec())
