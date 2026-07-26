from .common import *
import calendar as _pycalendar

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


class ScheduleAlertDialog(QDialog):
    def __init__(self, task_name, parent_pet, detail=""):
        super().__init__(parent_pet)
        self.pet = parent_pet
        self.setWindowTitle("🔔 日程提醒！")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        # 关闭后自动销毁，避免每提醒一次就在内存里留下一个永久窗口
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(320, 160)
        self.layout = QVBoxLayout(self)

        title = QLabel(f"<h2 style='color:red;'>到时间了：{task_name}</h2>")
        title.setWordWrap(True)
        self.layout.addWidget(title)

        if detail:
            d = QLabel(detail)
            d.setWordWrap(True)
            d.setStyleSheet("color:#555;")
            self.layout.addWidget(d)

        instruction = QLabel("快去执行你的待办事项。在面板中点击“已执行”可获得 20 数据碎片奖励。")
        instruction.setWordWrap(True)
        self.layout.addWidget(instruction)

        ok_btn = QPushButton("知道了")
        ok_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px; font-weight: bold;")
        ok_btn.clicked.connect(self.accept)
        self.layout.addWidget(ok_btn)

class CheckinAlertDialog(QDialog):
    """打卡提醒弹窗：可以直接在弹窗里打卡，不用再去开面板"""
    def __init__(self, item, parent_pet):
        super().__init__(parent_pet)
        self.pet = parent_pet
        self.item = item
        self.setWindowTitle("📌 打卡提醒")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(300, 150)
        lay = QVBoxLayout(self)

        lbl = QLabel(f"<h3>今天的「{item.get('name','')}」还没打卡。</h3>")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        if item.get("note"):
            note = QLabel(item["note"])
            note.setWordWrap(True)
            note.setStyleSheet("color:#666;")
            lay.addWidget(note)

        row = QHBoxLayout()
        ok = QPushButton("✅ 现在就打卡")
        ok.setStyleSheet("background-color:#4CAF50;color:white;padding:8px;font-weight:bold;")
        ok.clicked.connect(self.do_checkin)
        later = QPushButton("稍后")
        later.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(later)
        lay.addLayout(row)

    def do_checkin(self):
        self.accept()
        QTimer.singleShot(
            0, lambda pet=self.pet, item=self.item:
            pet.do_checkin(item, date.today(), True))

class EditScheduleDialog(QDialog):
    """
    ✏️ 新增/编辑日程。
    这里是“日程 ↔ 日历”联动的核心：可以自由选择是否绑定日期，
    绑定后还能设定 每天/每周/每月/每年/每N天 的重复周期。
    """
    def __init__(self, parent, sched=None, default_date=None, default_category=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.pet = parent.pet if hasattr(parent, "pet") else parent
        self.sched = sched                      # None 表示新建
        self.is_new = sched is None
        self.setWindowTitle("✏️ 编辑日程" if not self.is_new else "➕ 新建日程")
        self.resize(420, 400)
        lay = QVBoxLayout(self)

        form = QFormLayout()

        self.title_input = QLineEdit((sched or {}).get("task", ""))
        self.title_input.setPlaceholderText("标题，例如：交周报")
        form.addRow("标题：", self.title_input)

        self.cat_combo = QComboBox()
        self.cat_combo.addItems(CATEGORIES)
        cur_cat = (sched or {}).get("category", default_category or "日待办")
        if cur_cat in CATEGORIES:
            self.cat_combo.setCurrentIndex(CATEGORIES.index(cur_cat))
        form.addRow("分类：", self.cat_combo)

        t = QTime.fromString((sched or {}).get("time", ""), "HH:mm")
        self.time_edit = QTimeEdit(t if t.isValid() else QTime.currentTime())
        self.time_edit.setDisplayFormat("HH:mm")
        form.addRow("时间：", self.time_edit)

        # ---- 日期区（可选） ----
        date_row = QHBoxLayout()
        self.date_check = QCheckBox("绑定到具体日期")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        existing = parse_date((sched or {}).get("date", ""))
        base_d = existing or default_date or date.today()
        self.date_edit.setDate(QDate(base_d.year, base_d.month, base_d.day))
        self.date_check.setChecked(bool(existing) or (self.is_new and default_date is not None))
        self.date_check.toggled.connect(self.on_date_toggle)
        date_row.addWidget(self.date_check)
        date_row.addWidget(self.date_edit)
        form.addRow("日期：", date_row)

        rep_row = QHBoxLayout()
        self.repeat_combo = QComboBox()
        self.repeat_combo.addItems([txt for _, txt in REPEAT_LABELS])
        cur_rep = (sched or {}).get("repeat", "once")
        if cur_rep in REPEAT_KEYS:
            self.repeat_combo.setCurrentIndex(REPEAT_KEYS.index(cur_rep))
        self.repeat_combo.currentIndexChanged.connect(self.on_repeat_change)

        self.repeat_days = QSpinBox()
        self.repeat_days.setRange(1, 365)
        self.repeat_days.setSuffix(" 天一次")
        try:
            self.repeat_days.setValue(int((sched or {}).get("repeat_days", 1) or 1))
        except Exception:
            self.repeat_days.setValue(1)
        rep_row.addWidget(self.repeat_combo)
        rep_row.addWidget(self.repeat_days)
        form.addRow("重复：", rep_row)

        lay.addLayout(form)

        lay.addWidget(QLabel("详细内容（可留空）："))
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("补充说明、地点、要带的东西……")
        self.note_edit.setPlainText((sched or {}).get("note", ""))
        self.note_edit.setFixedHeight(110)
        lay.addWidget(self.note_edit)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#888;font-size:12px;")
        lay.addWidget(self.hint)

        btn = QPushButton("💾 保存")
        btn.setStyleSheet("background-color:#3F51B5;color:white;padding:8px;font-weight:bold;")
        btn.clicked.connect(self.save)
        lay.addWidget(btn)

        self.on_date_toggle(self.date_check.isChecked())
        self.setMinimumHeight(self.sizeHint().height())

    def on_date_toggle(self, checked):
        self.date_edit.setEnabled(checked)
        self.repeat_combo.setEnabled(checked)
        self.on_repeat_change()
        if checked:
            self.hint.setText("已绑定日期：会显示在日历对应格子里，按重复周期反复出现。")
        else:
            self.hint.setText("未绑定日期：作为通用待办显示在今天，每天到点提醒，直到你点“已执行”。")

    def on_repeat_change(self):
        is_custom = self.repeat_combo.currentIndex() == REPEAT_KEYS.index("custom")
        self.repeat_days.setEnabled(is_custom and self.date_check.isChecked())

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
            data.update({"id": new_id(), "status": "pending", "notified": False,
                         "alarm_on": True, "done_dates": []})
            self.pet.config.setdefault("schedules", []).append(data)
        else:
            self.sched.update(data)
            self.sched["notified"] = False  # 改过时间后，今天应该重新提醒
        self.accept()
        QTimer.singleShot(
            0, lambda pet=self.pet: (
                save_config(pet.config),
                pet.refresh_dialogs("dlg_ScheduleDialog", "dlg_MiniCalendarDialog", "dlg_StatsDialog")))

class EditCheckinDialog(QDialog):
    """➕ 新建 / ✏️ 编辑 每日打卡项目"""
    def __init__(self, parent, item=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.pet = parent.pet if hasattr(parent, "pet") else parent
        self.item = item
        self.is_new = item is None
        self.setWindowTitle("✏️ 编辑打卡项目" if not self.is_new else "➕ 新建打卡项目")
        self.resize(400, 330)
        lay = QVBoxLayout(self)

        form = QFormLayout()
        self.name_input = QLineEdit((item or {}).get("name", ""))
        self.name_input.setPlaceholderText("例如：喝够 2L 水 / 背 20 个单词")
        form.addRow("名称：", self.name_input)
        lay.addLayout(form)

        lay.addWidget(QLabel("备注（可留空）："))
        self.note_edit = QTextEdit()
        self.note_edit.setPlainText((item or {}).get("note", ""))
        self.note_edit.setFixedHeight(70)
        lay.addWidget(self.note_edit)

        reminder_label = QLabel("提醒时间（可留空；多个用英文逗号隔开，如 09:00,21:00）：")
        reminder_label.setWordWrap(True)
        lay.addWidget(reminder_label)
        self.times_input = QLineEdit(",".join((item or {}).get("remind_times", [])))
        self.times_input.setPlaceholderText("留空 = 不主动提醒")
        lay.addWidget(self.times_input)

        self.enable_check = QCheckBox("启用（关闭后不再提醒、也不计入每日全勤）")
        self.enable_check.setChecked((item or {}).get("enabled", True))
        lay.addWidget(self.enable_check)

        btn = QPushButton("💾 保存")
        btn.setStyleSheet("background-color:#3F51B5;color:white;padding:8px;font-weight:bold;")
        btn.clicked.connect(self.save)
        lay.addWidget(btn)

    def save(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "名称不能为空。")
            return
        times = []
        for raw in self.times_input.text().replace("，", ",").split(","):
            raw = raw.strip()
            if not raw:
                continue
            qt = QTime.fromString(raw, "HH:mm")
            if qt.isValid():
                times.append(qt.toString("HH:mm"))
            else:
                QMessageBox.warning(self, "时间格式不对", f"「{raw}」看不懂，请用 09:00 这种写法。")
                return
        data = {"name": name, "note": self.note_edit.toPlainText().strip(),
                "remind_times": times, "enabled": self.enable_check.isChecked()}
        if self.is_new:
            data.update({"id": new_id(), "created": today_str(), "done_dates": [], "archived": False})
            self.pet.config.setdefault("checkins", []).append(data)
        else:
            self.item.update(data)
        self.accept()
        QTimer.singleShot(
            0, lambda pet=self.pet: (
                save_config(pet.config),
                pet.refresh_dialogs("dlg_CheckinDialog", "dlg_MiniCalendarDialog", "dlg_StatsDialog")))

class ScheduleDialog(QDialog):
    def __init__(self, parent_pet):
        super().__init__(parent_pet)
        self.pet = parent_pet
        self.setWindowTitle("Giegisa - 传达者日程系统")
        self.setMinimumSize(430, 500)
        self.resize(640, 600)
        self.layout = QVBoxLayout(self)
        
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("📂 分类:"))
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(CATEGORIES)
        self.cat_combo.currentIndexChanged.connect(self.on_cat_changed)
        top_layout.addWidget(self.cat_combo, stretch=1)
        
        top_layout.addWidget(QLabel("↕️ 排序:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["拖拽排序 (自定义)", "时间最早优先", "时间最晚优先", "按日期先后"])
        self.sort_combo.currentIndexChanged.connect(self.refresh_list)
        top_layout.addWidget(self.sort_combo, stretch=1)
        self.layout.addLayout(top_layout)

        nav_layout = QHBoxLayout()
        nav_layout.addStretch()
        self.cal_btn = QPushButton("📅 日历")
        self.cal_btn.setToolTip("打开迷你月历")
        self.cal_btn.clicked.connect(lambda: self.pet.open_dialog(MiniCalendarDialog))
        nav_layout.addWidget(self.cal_btn)
        self.layout.addLayout(nav_layout)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("🔍 搜索标题或内容…")
        self.filter_input.textChanged.connect(self.refresh_list)
        self.layout.addWidget(self.filter_input)
        
        # 使用新增的拖拽列表控件
        self.list_widget = DraggableListWidget()
        self.list_widget.order_updated.connect(self.reorder_schedules)
        self.layout.addWidget(self.list_widget)
        
        self.toggle_hidden_btn = QPushButton("🔽 显示当前分类的隐藏项")
        self.toggle_hidden_btn.setCheckable(True)
        self.toggle_hidden_btn.setStyleSheet("color: gray; border: none; text-align: left;")
        self.toggle_hidden_btn.toggled.connect(self.toggle_hidden)
        self.layout.addWidget(self.toggle_hidden_btn)
        
        self.hidden_list_widget = ResponsiveListWidget()
        self.hidden_list_widget.hide()
        self.layout.addWidget(self.hidden_list_widget)
        
        quick_fields = QHBoxLayout()
        self.time_edit = QTimeEdit(QTime.currentTime())
        self.time_edit.setDisplayFormat("HH:mm")
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("在此输入待办事项...")
        self.task_input.returnPressed.connect(self.add_schedule)
        quick_fields.addWidget(self.time_edit)
        quick_fields.addWidget(self.task_input, stretch=1)
        self.layout.addLayout(quick_fields)
        
        add_layout = QHBoxLayout()
        add_layout.addStretch()
        add_btn = QPushButton("➕快速添加")
        add_btn.setToolTip("快速添加一条“不绑定日期”的待办")
        add_btn.clicked.connect(self.add_schedule)

        detail_btn = QPushButton("📝详细添加")
        detail_btn.setToolTip("可以设定日期、重复周期和详细内容")
        detail_btn.clicked.connect(self.add_detailed)
        
        add_layout.addWidget(add_btn)
        add_layout.addWidget(detail_btn)
        self.layout.addLayout(add_layout)

        speak_btn = QPushButton("💬 让 Giegisa 说说今天的安排（基于真实数据，不会瞎编）")
        speak_btn.setStyleSheet("padding:6px;")
        speak_btn.clicked.connect(lambda: self.pet.speak_today_plan())
        self.layout.addWidget(speak_btn)
        
        self.refresh_list()

    def on_cat_changed(self):
        # 切换分类时，自动收起隐藏栏，实现视觉隔离
        self.toggle_hidden_btn.setChecked(False) 
        self.refresh_list()
        
    def toggle_hidden(self, checked):
        if checked:
            self.hidden_list_widget.show()
            self.toggle_hidden_btn.setText("🔼 收起当前分类的隐藏项")
        else:
            self.hidden_list_widget.hide()
            self.toggle_hidden_btn.setText("🔽 显示当前分类的隐藏项")

    def reorder_schedules(self, new_ids):
        """拖拽排序：只调整“当前可见的这一批”在总表里的先后顺序，其它条目原地不动。"""
        schedules = self.pet.config.get("schedules", [])
        curr_cat = self.cat_combo.currentText()

        # 用 id 定位，而不是用 dict 的值比较（值比较在内容相同时会认错条目）
        visible_ids = [s.get("id") for s in schedules
                       if s.get("category", "日待办") == curr_cat and s.get("status") != "hidden"]
        id_map = {s.get("id"): s for s in schedules}
        ordered = [id_map[i] for i in new_ids if i in id_map]
        if sorted([id(x) for x in ordered]) != sorted([id(id_map[i]) for i in visible_ids if i in id_map]):
            # 拖拽结果和实际可见项对不上（理论上不该发生），放弃这次重排，保数据安全
            self.refresh_list()
            return

        slots = [i for i, s in enumerate(schedules) if s.get("id") in visible_ids]
        for slot, obj in zip(slots, ordered):
            schedules[slot] = obj
        save_config(self.pet.config)
        self.refresh_list()

    def refresh_list(self):
        curr_cat = self.cat_combo.currentText()
        kw = self.filter_input.text().strip().lower()
        self.list_widget.clear()
        self.hidden_list_widget.clear()
        
        visible_scheds = []
        hidden_scheds = []
        for sched in self.pet.config.get("schedules", []):
            if not isinstance(sched, dict):
                continue
            if sched.get("category", "日待办") != curr_cat:
                continue
            if kw and kw not in str(sched.get("task", "")).lower() and kw not in str(sched.get("note", "")).lower():
                continue
            if sched.get("status") == "hidden":
                hidden_scheds.append(sched)
            else:
                visible_scheds.append(sched)
                
        # 排序（用 .get 兜底，缺字段的脏数据也不会让整个面板崩掉）
        sort_idx = self.sort_combo.currentIndex()
        if sort_idx == 1:
            visible_scheds.sort(key=lambda x: str(x.get("time", "99:99")))
        elif sort_idx == 2:
            visible_scheds.sort(key=lambda x: str(x.get("time", "00:00")), reverse=True)
        elif sort_idx == 3:
            visible_scheds.sort(key=lambda x: (str(x.get("date", "9999-99-99") or "9999-99-99"),
                                               str(x.get("time", "99:99"))))
            
        self.render_items(visible_scheds, self.list_widget, allow_drag=(sort_idx == 0))
        self.render_items(hidden_scheds, self.hidden_list_widget, allow_drag=False)

        # 空数据提示：原来空列表是一片空白，容易让人以为程序坏了
        if not visible_scheds:
            tip = "🔍 没有匹配的日程。" if kw else f"📭 「{curr_cat}」里还没有日程，在下面添加一条吧。"
            self.list_widget.addItem(tip)

    def _describe(self, sched):
        """把日期/重复规则翻译成人话"""
        ds = sched.get("date", "")
        if not ds:
            return "无日期·每天提醒"
        rep = sched.get("repeat", "once")
        if rep == "once":
            return f"{ds}"
        if rep == "custom":
            return f"{ds} 起 · 每{sched.get('repeat_days', 1)}天"
        return f"{ds} 起 · {REPEAT_TEXT.get(rep, rep)}"

    def render_items(self, sched_list, target_widget, allow_drag):
        today = date.today()
        for sched in sched_list:
            item_widget = QWidget()
            item_layout = QVBoxLayout(item_widget)
            item_layout.setContentsMargins(6, 4, 6, 4)
            item_layout.setSpacing(4)
            actions = QGridLayout()
            actions.setContentsMargins(0, 0, 0, 0)
            actions.setSpacing(4)
            action_buttons = []

            recurring = sched_is_recurring(sched)
            done_today = sched_done_on(sched, today)
            mark = "✔ 今日已完成" if (recurring and done_today) else \
                   ("⏳ 待执行" if sched.get("status") == "pending" else
                    f"✔ 完成于 {sched.get('completed_time', '')}")

            note = sched.get("note", "")
            note_line = f"<br><span style='color:#777;font-size:12px;'>{note[:60]}{'…' if len(note) > 60 else ''}</span>" if note else ""
            lbl_txt = (f"[{sched.get('time', '--:--')}] {sched.get('task', '')} ({mark})"
                       f"<br><span style='color:#4169E1;font-size:12px;'>📅 {self._describe(sched)}</span>{note_line}")
                
            lbl = QLabel(lbl_txt)
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            item_layout.addWidget(lbl)
            
            if sched.get("status") == "pending":
                # 单独的铃声开关
                btn_alarm = QPushButton("提醒开" if sched.get("alarm_on", True) else "提醒关")
                btn_alarm.setMinimumWidth(58)
                btn_alarm.setToolTip("开启/关闭该项的到点提醒")
                btn_alarm.clicked.connect(lambda checked=False, s=sched: self.toggle_alarm(s))
                action_buttons.append(btn_alarm)

                btn_edit = QPushButton("编辑")
                btn_edit.setMinimumWidth(48)
                btn_edit.setToolTip("修改标题 / 内容 / 时间 / 日期 / 重复周期")
                btn_edit.clicked.connect(lambda checked=False, s=sched: self.edit_task(s))
                action_buttons.append(btn_edit)

                if recurring and done_today:
                    btn_done = QPushButton("撤销今日")
                    btn_done.clicked.connect(lambda checked=False, s=sched: self.mark_done(s, False))
                else:
                    btn_done = QPushButton("已执行")
                    btn_done.setStyleSheet("background-color: #4CAF50; color: white;")
                    btn_done.clicked.connect(lambda checked=False, s=sched: self.mark_done(s, True))
                action_buttons.append(btn_done)
            elif sched.get("status") == "completed":
                btn_edit = QPushButton("编辑")
                btn_edit.setMinimumWidth(48)
                btn_edit.clicked.connect(lambda checked=False, s=sched: self.edit_task(s))
                action_buttons.append(btn_edit)

                btn_undo = QPushButton("↩︎重开")
                btn_undo.setToolTip("标记回未完成")
                btn_undo.clicked.connect(lambda checked=False, s=sched: self.mark_done(s, False))
                action_buttons.append(btn_undo)

                btn_hide = QPushButton("不显示")
                btn_hide.clicked.connect(lambda checked=False, s=sched: self.hide_task(s))
                action_buttons.append(btn_hide)
            else:
                btn_restore = QPushButton("↩︎恢复")
                btn_restore.clicked.connect(lambda checked=False, s=sched: self.restore_task(s))
                action_buttons.append(btn_restore)
                
            btn_del = QPushButton("删除")
            btn_del.setMinimumWidth(48)
            btn_del.clicked.connect(lambda checked=False, s=sched: self.del_task(s))
            action_buttons.append(btn_del)
            for index, button in enumerate(action_buttons):
                button.setMinimumHeight(34)
                button.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                actions.addWidget(button, index // 2, index % 2)
            item_layout.addLayout(actions)
            
            item = QListWidgetItem()
            item.setSizeHint(item_widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, sched.get("id"))
            
            if allow_drag:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsDropEnabled)
                
            target_widget.addItem(item)
            target_widget.setItemWidget(item, item_widget)

    def toggle_alarm(self, sched):
        sched["alarm_on"] = not sched.get("alarm_on", True)
        save_config(self.pet.config)
        self.refresh_list()

    def edit_task(self, sched):
        dlg = EditScheduleDialog(self, sched=sched)
        dlg.show()

    def mark_done(self, sched, done=True):
        self.pet.mark_schedule_done(sched, date.today(), done)
        self.refresh_list()

    def hide_task(self, sched):
        sched["status"] = "hidden"
        save_config(self.pet.config)
        self.refresh_list()

    def restore_task(self, sched):
        sched["status"] = "pending"
        save_config(self.pet.config)
        self.refresh_list()

    def del_task(self, sched):
        if QMessageBox.question(self, "确认删除", f"确定删除「{sched.get('task','')}」吗？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                ) != QMessageBox.StandardButton.Yes:
            return
        # 按 id 精确删除，避免内容相同时删错条目
        sid = sched.get("id")
        lst = self.pet.config.get("schedules", [])
        for i, s in enumerate(lst):
            if s.get("id") == sid:
                del lst[i]
                break
        save_config(self.pet.config)
        self.pet.refresh_dialogs("dlg_MiniCalendarDialog", "dlg_StatsDialog")
        self.refresh_list()

    def add_detailed(self):
        dlg = EditScheduleDialog(self, default_category=self.cat_combo.currentText())
        dlg.show()

    def add_schedule(self):
        task = self.task_input.text().strip()
        if not task:
            return
        self.pet.config.setdefault("schedules", []).append({
            "id": new_id(),
            "category": self.cat_combo.currentText(),
            "time": self.time_edit.time().toString("HH:mm"),
            "task": task,
            "note": "",
            "date": "",          # 快速添加默认不绑定日期
            "repeat": "once",
            "repeat_days": 1,
            "done_dates": [],
            "notified": False,
            "status": "pending",
            "alarm_on": True
        })
        save_config(self.pet.config)
        self.task_input.clear()
        self.pet.refresh_dialogs("dlg_MiniCalendarDialog", "dlg_StatsDialog")
        self.refresh_list()

class DayDetailDialog(QDialog):
    """点击日历格子后弹出的迷你详情窗：显示当天的日程与打卡，可直接勾选/编辑/新增"""
    def __init__(self, parent, the_date):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.pet = parent.pet if hasattr(parent, "pet") else parent
        self.the_date = the_date
        self.setWindowTitle(the_date.strftime("%Y年%m月%d日"))
        self.setWindowFlags(Qt.WindowType.Tool)
        self.setMinimumSize(360, 420)
        self.resize(400, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        self.title = QLabel()
        self.title.setStyleSheet("font-weight:bold;font-size:14px;")
        lay.addWidget(self.title)

        self.list_widget = ResponsiveListWidget()
        lay.addWidget(self.list_widget)

        row = QHBoxLayout()
        add_btn = QPushButton("➕ 加日程")
        add_btn.clicked.connect(self.add_here)
        speak_btn = QPushButton("💬 让它念")
        speak_btn.setToolTip("让 Giegisa 用这一天的真实安排说句话")
        speak_btn.clicked.connect(self.speak)
        row.addWidget(add_btn)
        row.addWidget(speak_btn)
        lay.addLayout(row)

        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        d = self.the_date
        items = schedules_of_day(self.pet.config, d)
        checks = active_checkins(self.pet.config) if d == date.today() else []
        done_n = sum(1 for s in items if sched_done_on(s, d))
        self.title.setText(f"{d.strftime('%m月%d日')} · 日程 {done_n}/{len(items)}")

        if not items and not checks:
            self.list_widget.addItem("📭 这一天没有安排。")
            return

        for s in items:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(2, 2, 2, 2)
            cb = QCheckBox()
            cb.setChecked(sched_done_on(s, d))
            cb.toggled.connect(lambda v, sc=s: self.toggle(sc, v))
            note = s.get("note", "")
            txt = f"<b>{s.get('time', '--:--')}</b> {s.get('task', '')}"
            if note:
                txt += f"<br><span style='color:#777;font-size:11px;'>{note[:40]}</span>"
            lbl = QLabel(txt)
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            edit = QPushButton("编辑")
            edit.setMinimumSize(62, 34)
            edit.clicked.connect(lambda checked=False, sc=s: self.edit(sc))
            h.addWidget(cb)
            h.addWidget(lbl, stretch=1)
            h.addWidget(edit)
            w.setMinimumHeight(62)
            it = QListWidgetItem()
            it.setSizeHint(w.sizeHint())
            self.list_widget.addItem(it)
            self.list_widget.setItemWidget(it, w)

        if checks:
            self.list_widget.addItem("—— 今日打卡 ——")
            for c in checks:
                w = QWidget()
                h = QHBoxLayout(w)
                h.setContentsMargins(2, 2, 2, 2)
                cb = QCheckBox(c.get("name", ""))
                cb.setChecked(checkin_done_on(c, d))
                cb.toggled.connect(lambda v, ci=c: self.pet.do_checkin(ci, self.the_date, v))
                h.addWidget(cb, stretch=1)
                w.setMinimumHeight(54)
                it = QListWidgetItem()
                it.setSizeHint(w.sizeHint())
                self.list_widget.addItem(it)
                self.list_widget.setItemWidget(it, w)

    def toggle(self, sched, val):
        self.pet.mark_schedule_done(sched, self.the_date, val)
        self.refresh_list()

    def edit(self, sched):
        EditScheduleDialog(self, sched=sched).show()

    def add_here(self):
        EditScheduleDialog(self, default_date=self.the_date).show()

    def speak(self):
        self.pet.speak_today_plan(self.the_date)

class MiniCalendarDialog(QDialog):
    """
    📅 迷你月历（约 200px 宽）。
    - 有日程的日子会用不同底色标出：蓝=还有没做完的，绿=当天的都完成了
    - 点日期：上方列表切换到那一天，同时桌宠会念出当天安排
    - 双击日期：弹出独立的详情小窗
    """
    CELL = 26

    def __init__(self, parent_pet):
        super().__init__(parent_pet)
        self.pet = parent_pet
        self.setWindowTitle("📅 日历")
        self.setWindowFlags(Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.sel_date = date.today()
        self.view_year = self.sel_date.year
        self.view_month = self.sel_date.month
        # 不锁死 236px：Windows 字体、DPI 缩放不同，实际最小内容宽度可能
        # 达到 270px 左右。允许窗口变宽，避免“今天”、月份和底部按钮被截断。
        self.setMinimumSize(340, 600)
        self.resize(360, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ---- 上方：当天日程 / 打卡列表（对应你效果图里的上半部分）----
        self.day_title = QLabel()
        self.day_title.setStyleSheet("font-weight:bold;font-size:13px;color:#333;")
        root.addWidget(self.day_title)

        self.day_list = ResponsiveListWidget()
        self.day_list.setMinimumHeight(150)
        self.day_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.day_list.setStyleSheet("QListWidget{background:#eef3fb;border:1px solid #cfd9ea;border-radius:6px;}")
        root.addWidget(self.day_list)

        # ---- 中间：月历头 ----
        head = QHBoxLayout()
        prev_btn = QPushButton("◀")
        prev_btn.setMinimumWidth(34)
        prev_btn.clicked.connect(lambda: self.shift_month(-1))
        self.head_label = QLabel()
        self.head_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.head_label.setStyleSheet("font-weight:bold;color:#2f6fd0;")
        next_btn = QPushButton("▶")
        next_btn.setMinimumWidth(34)
        next_btn.clicked.connect(lambda: self.shift_month(1))
        today_btn = QPushButton("今天")
        today_btn.setMinimumWidth(52)
        today_btn.clicked.connect(self.go_today)
        head.addWidget(prev_btn)
        head.addWidget(self.head_label, stretch=1)
        head.addWidget(next_btn)
        head.addWidget(today_btn)
        root.addLayout(head)

        # ---- 中间：7x6 日期格 ----
        self.grid = QGridLayout()
        self.grid.setSpacing(2)
        week_start = int(self.pet.config.get("calendar_week_start", 0) or 0)
        names = ["一", "二", "三", "四", "五", "六", "日"] if week_start == 0 else \
                ["日", "一", "二", "三", "四", "五", "六"]
        for c, n in enumerate(names):
            l = QLabel(n)
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setStyleSheet("color:#888;font-size:11px;")
            self.grid.addWidget(l, 0, c)

        self.cells = []
        for r in range(6):
            row = []
            for c in range(7):
                b = QPushButton("")
                b.setProperty("calendarCell", True)
                b.setFixedSize(self.CELL + 4, self.CELL)
                b.setFlat(True)
                b.clicked.connect(lambda checked=False, rr=r, cc=c: self.on_cell(rr, cc))
                self.grid.addWidget(b, r + 1, c)
                row.append(b)
            self.cells.append(row)
        root.addLayout(self.grid)

        # ---- 底部按钮 ----
        row1 = QHBoxLayout()
        b_add = QPushButton("➕ 加日程")
        b_add.clicked.connect(self.add_on_selected)
        b_detail = QPushButton("🔍 详情窗")
        b_detail.clicked.connect(self.open_detail)
        row1.addWidget(b_add)
        row1.addWidget(b_detail)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        b_check = QPushButton("📌 打卡")
        b_check.clicked.connect(lambda: self.pet.open_dialog(CheckinDialog))
        b_stat = QPushButton("📊 统计")
        b_stat.clicked.connect(lambda: self.pet.open_dialog(StatsDialog))
        row2.addWidget(b_check)
        row2.addWidget(b_stat)
        root.addLayout(row2)

        b_speak = QPushButton("💬 让 Giegisa 说说这天")
        b_speak.setStyleSheet("padding:4px;")
        b_speak.clicked.connect(lambda: self.pet.speak_today_plan(self.sel_date))
        root.addWidget(b_speak)

        self.refresh_list()

    # -------- 数据 --------
    def _day_state(self, d):
        """返回 (日程总数, 已完成数)"""
        items = schedules_of_day(self.pet.config, d)
        if not items:
            return 0, 0
        return len(items), sum(1 for s in items if sched_done_on(s, d))

    def refresh_list(self):
        self.head_label.setText(f"{self.view_year}年 {self.view_month}月")
        week_start = int(self.pet.config.get("calendar_week_start", 0) or 0)
        cal = _pycalendar.Calendar(firstweekday=0 if week_start == 0 else 6)
        weeks = cal.monthdatescalendar(self.view_year, self.view_month)
        today = date.today()

        for r in range(6):
            for c in range(7):
                btn = self.cells[r][c]
                if r >= len(weeks):
                    btn.setText("")
                    btn.setEnabled(False)
                    btn.setStyleSheet("border:none;background:transparent;")
                    btn.setProperty("theDate", None)
                    continue
                d = weeks[r][c]
                btn.setEnabled(True)
                btn.setText(str(d.day))
                btn.setProperty("theDate", d.strftime("%Y-%m-%d"))

                in_month = (d.month == self.view_month)
                total, done = self._day_state(d)

                if total == 0:
                    bg, fg = "transparent", ("#333333" if in_month else "#bbbbbb")
                elif done >= total:
                    bg, fg = "#7ed09a", "#ffffff"          # 全部完成 → 绿
                else:
                    bg, fg = "#4a90e2", "#ffffff"          # 还有没做完 → 蓝
                if not in_month and total > 0:
                    bg = "#c9dcf5"
                    fg = "#ffffff"

                border = "2px solid #ff8c42" if d == today else "1px solid transparent"
                if d == self.sel_date and d != today:
                    border = "2px solid #2f6fd0"
                btn.setStyleSheet(
                    f"QPushButton{{background:{bg};color:{fg};border:{border};"
                    f"border-radius:5px;font-size:11px;font-weight:bold;}}"
                    f"QPushButton:hover{{background:#dfe9f7;color:#333;}}")
                btn.setToolTip(f"{d.strftime('%Y-%m-%d')}  待办 {done}/{total}" if total else d.strftime("%Y-%m-%d"))

        self.refresh_day_panel()

    def refresh_day_panel(self):
        d = self.sel_date
        self.day_list.clear()
        items = schedules_of_day(self.pet.config, d)
        total, done = len(items), sum(1 for s in items if sched_done_on(s, d))
        self.day_title.setText(f"📋 {d.strftime('%m月%d日')} · {done}/{total} 完成")

        checks = active_checkins(self.pet.config) if d == date.today() else []
        if not items and not checks:
            self.day_list.addItem("📭 这天没有安排")
            return

        for s in items:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(4, 1, 4, 1)
            cb = QCheckBox()
            cb.setChecked(sched_done_on(s, d))
            cb.toggled.connect(lambda v, sc=s: self.toggle_done(sc, v))
            lbl = QLabel(f"<b>{s.get('time', '--:--')}</b> {s.get('task', '')}")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            w.setMinimumHeight(42)
            h.addWidget(cb)
            h.addWidget(lbl, stretch=1)
            it = QListWidgetItem()
            it.setSizeHint(w.sizeHint())
            self.day_list.addItem(it)
            self.day_list.setItemWidget(it, w)

        for c in checks:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(4, 1, 4, 1)
            cb = QCheckBox("📌 " + c.get("name", ""))
            cb.setChecked(checkin_done_on(c, d))
            cb.toggled.connect(lambda v, ci=c: self.on_checkin(ci, v))
            h.addWidget(cb, stretch=1)
            w.setMinimumHeight(42)
            it = QListWidgetItem()
            it.setSizeHint(w.sizeHint())
            self.day_list.addItem(it)
            self.day_list.setItemWidget(it, w)

    # -------- 交互 --------
    def toggle_done(self, sched, val):
        self.pet.mark_schedule_done(sched, self.sel_date, val)
        self.refresh_list()

    def on_checkin(self, item, val):
        self.pet.do_checkin(item, self.sel_date, val)
        self.refresh_list()

    def shift_month(self, delta):
        m = self.view_month + delta
        y = self.view_year
        while m < 1:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1
        self.view_year, self.view_month = y, m
        self.refresh_list()

    def go_today(self):
        t = date.today()
        self.view_year, self.view_month, self.sel_date = t.year, t.month, t
        self.refresh_list()

    def on_cell(self, r, c):
        raw = self.cells[r][c].property("theDate")
        d = parse_date(raw)
        if not d:
            return
        self.sel_date = d
        if d.month != self.view_month:
            self.view_year, self.view_month = d.year, d.month
        self.refresh_list()
        # 需求②：点了有安排的日子，桌宠说出安排内容
        if schedules_of_day(self.pet.config, d):
            self.pet.speak_today_plan(d)

    def add_on_selected(self):
        EditScheduleDialog(self, default_date=self.sel_date).show()

    def open_detail(self):
        dlg = DayDetailDialog(self, self.sel_date)
        dlg.move(self.x() + self.width() + 10, self.y())
        dlg.show()
        self._detail = dlg

class CheckinDialog(QDialog):
    """📌 每日打卡：每天 0 点自动翻篇，全部完成有额外碎片奖励"""
    def __init__(self, parent_pet):
        super().__init__(parent_pet)
        self.pet = parent_pet
        self.setWindowTitle("📌 每日打卡")
        self.setMinimumSize(360, 420)
        self.resize(480, 520)
        lay = QVBoxLayout(self)

        self.header = QLabel()
        self.header.setStyleSheet("font-size:14px;font-weight:bold;")
        lay.addWidget(self.header)

        self.list_widget = ResponsiveListWidget()
        lay.addWidget(self.list_widget)

        self.show_archived = QPushButton("🔽 显示已归档的打卡项")
        self.show_archived.setCheckable(True)
        self.show_archived.setStyleSheet("color:gray;border:none;text-align:left;")
        self.show_archived.toggled.connect(self.refresh_list)
        lay.addWidget(self.show_archived)

        row = QHBoxLayout()
        add_btn = QPushButton("➕ 新建打卡项目")
        add_btn.setStyleSheet("background-color:#4CAF50;color:white;padding:8px;font-weight:bold;")
        add_btn.clicked.connect(self.add_item)
        stat_btn = QPushButton("📊 查看统计")
        stat_btn.clicked.connect(lambda: self.pet.open_dialog(StatsDialog))
        row.addWidget(add_btn)
        row.addWidget(stat_btn)
        lay.addLayout(row)

        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        d = date.today()
        show_arc = self.show_archived.isChecked()
        items = [c for c in self.pet.config.get("checkins", [])
                 if isinstance(c, dict) and (show_arc or not c.get("archived"))]

        act = active_checkins(self.pet.config)
        done = sum(1 for c in act if checkin_done_on(c, d))
        self.header.setText(f"今天（{d.strftime('%m月%d日')}）已完成 {done} / {len(act)} 项"
                            + ("　🎉 全勤达成！" if act and done >= len(act) else ""))

        if not items:
            self.list_widget.addItem("📭 还没有打卡项目。点下面的按钮建一个，比如“喝水”“背单词”。")
            return

        for c in items:
            w = QWidget()
            item_layout = QVBoxLayout(w)
            item_layout.setContentsMargins(6, 4, 6, 4)
            item_layout.setSpacing(4)
            content = QHBoxLayout()
            actions = QGridLayout()
            actions.setSpacing(6)

            cb = QCheckBox()
            cb.setChecked(checkin_done_on(c, d))
            cb.setEnabled(not c.get("archived", False))
            cb.toggled.connect(lambda v, ci=c: self.toggle(ci, v))

            streak = checkin_streak(c, d)
            times = "，".join(c.get("remind_times", [])) or "不提醒"
            state = "（已归档）" if c.get("archived") else ("" if c.get("enabled", True) else "（已停用）")
            txt = (f"<b>{c.get('name','')}</b>{state}"
                   f"<br><span style='color:#777;font-size:12px;'>🔥 连续 {streak} 天　⏰ {times}</span>")
            if c.get("note"):
                txt += f"<br><span style='color:#999;font-size:11px;'>{c['note'][:50]}</span>"
            lbl = QLabel(txt)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

            edit = QPushButton("编辑")
            edit.setMinimumSize(58, 34)
            edit.clicked.connect(lambda checked=False, ci=c: self.edit(ci))

            arc = QPushButton("恢复" if c.get("archived") else "归档")
            arc.setMinimumSize(58, 34)
            arc.setToolTip("归档 / 取消归档（归档后保留历史记录，但不再参与每日统计）")
            arc.clicked.connect(lambda checked=False, ci=c: self.toggle_archive(ci))

            dele = QPushButton("删除")
            dele.setMinimumSize(58, 34)
            dele.clicked.connect(lambda checked=False, ci=c: self.delete(ci))

            content.addWidget(cb)
            content.addWidget(lbl, stretch=1)
            for index, button in enumerate((edit, arc, dele)):
                button.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                actions.addWidget(button, 0, index)
            item_layout.addLayout(content)
            item_layout.addLayout(actions)

            it = QListWidgetItem()
            it.setSizeHint(w.sizeHint())
            self.list_widget.addItem(it)
            self.list_widget.setItemWidget(it, w)

    def toggle(self, item, val):
        self.pet.do_checkin(item, date.today(), val)
        self.refresh_list()

    def add_item(self):
        EditCheckinDialog(self).show()

    def edit(self, item):
        EditCheckinDialog(self, item=item).show()

    def toggle_archive(self, item):
        item["archived"] = not item.get("archived", False)
        save_config(self.pet.config)
        self.refresh_list()

    def delete(self, item):
        if QMessageBox.question(
                self, "确认删除",
                f"删除「{item.get('name','')}」会连同它的打卡历史一起消失，确定吗？\n"
                f"（如果只是暂时不做了，建议用 📦 归档）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        cid = item.get("id")
        lst = self.pet.config.get("checkins", [])
        for i, c in enumerate(lst):
            if c.get("id") == cid:
                del lst[i]
                break
        save_config(self.pet.config)
        self.pet.refresh_dialogs("dlg_MiniCalendarDialog", "dlg_StatsDialog")
        self.refresh_list()

class StatsDialog(QDialog):
    """📊 简单统计：今日情况 + 近一段时间的完成量（纯文字+色条，不引入任何绘图库）"""
    RANGES = [("最近 7 天", 7), ("最近 30 天", 30), ("最近 90 天", 90)]

    def __init__(self, parent_pet):
        super().__init__(parent_pet)
        self.pet = parent_pet
        self.setWindowTitle("📊 日程与打卡统计")
        self.resize(520, 560)
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("统计范围："))
        self.range_combo = QComboBox()
        self.range_combo.addItems([t for t, _ in self.RANGES])
        self.range_combo.setCurrentIndex(1)
        self.range_combo.currentIndexChanged.connect(self.refresh_list)
        top.addWidget(self.range_combo)
        top.addStretch()
        refresh = QPushButton("🔄 刷新")
        refresh.clicked.connect(self.refresh_list)
        top.addWidget(refresh)
        lay.addLayout(top)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.body = QLabel()
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setWordWrap(True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body.setStyleSheet("padding:10px;font-family:'Microsoft YaHei';font-size:13px;")
        self.area.setWidget(self.body)
        lay.addWidget(self.area)

        speak = QPushButton("💬 让 Giegisa 点评一下这段时间")
        speak.setStyleSheet("padding:8px;")
        speak.clicked.connect(self.speak_review)
        lay.addWidget(speak)

        self.refresh_list()

    def _collect(self, days):
        today = date.today()
        rows = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            items = schedules_of_day(self.pet.config, d)
            total = len(items)
            done = sum(1 for s in items if sched_done_on(s, d))
            acts = active_checkins(self.pet.config)
            c_total = len(acts)
            c_done = sum(1 for c in acts if checkin_done_on(c, d))
            rows.append((d, total, done, c_total, c_done))
        return rows

    @staticmethod
    def _bar(done, total, width=16):
        if total <= 0:
            return "<span style='color:#ccc'>—</span>"
        filled = int(round(width * done / total))
        color = "#7ed09a" if done >= total else "#4a90e2"
        return (f"<span style='color:{color}'>{'█' * filled}</span>"
                f"<span style='color:#e2e6ec'>{'█' * (width - filled)}</span>")

    def refresh_list(self):
        days = self.RANGES[self.range_combo.currentIndex()][1]
        rows = self._collect(days)
        today = date.today()

        acts = active_checkins(self.pet.config)
        today_items = schedules_of_day(self.pet.config, today)
        t_done = sum(1 for s in today_items if sched_done_on(s, today))
        c_done = sum(1 for c in acts if checkin_done_on(c, today))

        html = ["<h3>📅 今天</h3>"]
        html.append(f"<p>待办：<b>{t_done} / {len(today_items)}</b> 　 {self._bar(t_done, len(today_items))}</p>")
        html.append(f"<p>打卡：<b>{c_done} / {len(acts)}</b> 　 {self._bar(c_done, len(acts))}"
                    + ("　<span style='color:#4CAF50'><b>🎉 今日全勤</b></span>" if acts and c_done >= len(acts) else "")
                    + "</p>")

        total_done = sum(r[2] for r in rows)
        total_all = sum(r[1] for r in rows)
        cd = sum(r[4] for r in rows)
        ca = sum(r[3] for r in rows)
        rate = f"{(total_done / total_all * 100):.0f}%" if total_all else "—"
        crate = f"{(cd / ca * 100):.0f}%" if ca else "—"

        html.append(f"<h3>📈 最近 {days} 天</h3>")
        html.append(f"<p>待办完成 <b>{total_done}</b> 个（共 {total_all} 个，完成率 <b>{rate}</b>）<br>"
                    f"打卡完成 <b>{cd}</b> 次（共 {ca} 次，完成率 <b>{crate}</b>）</p>")

        if acts:
            html.append("<h3>🔥 各项打卡连续天数</h3><p>")
            for c in acts:
                s = checkin_streak(c, today)
                html.append(f"{c.get('name','')}：<b>{s}</b> 天　")
            html.append("</p>")

        st = self.pet.config.get("stats", {})
        html.append(f"<h3>🏆 累计</h3><p>历史完成待办 <b>{st.get('todo_done_total', 0)}</b> 个　|　"
                    f"历史打卡 <b>{st.get('checkin_done_total', 0)}</b> 次</p>")

        html.append(f"<h3>📊 每日明细（近 {min(days, 30)} 天）</h3>")
        html.append("<table cellspacing='0' cellpadding='3' style='font-size:12px;'>")
        html.append("<tr style='color:#888'><td>日期</td><td>待办</td><td></td><td>打卡</td><td></td></tr>")
        for d, tot, dn, ct, cdn in rows[-30:]:
            mark = "  ◀今天" if d == today else ""
            html.append(f"<tr><td>{d.strftime('%m-%d')}{mark}</td>"
                        f"<td>{dn}/{tot}</td><td>{self._bar(dn, tot, 10)}</td>"
                        f"<td>{cdn}/{ct}</td><td>{self._bar(cdn, ct, 10)}</td></tr>")
        html.append("</table>")

        if not today_items and not acts and total_all == 0:
            html = ["<h3>📭 还没有任何数据</h3>"
                    "<p>先在「日程系统」里加几条待办，或者在「每日打卡」里建一个打卡项目，"
                    "这里就会开始记录了。</p>"]

        self.body.setText("".join(html))

    def speak_review(self):
        days = self.RANGES[self.range_combo.currentIndex()][1]
        rows = self._collect(days)
        total_done = sum(r[2] for r in rows)
        total_all = sum(r[1] for r in rows)
        cd = sum(r[4] for r in rows)
        ca = sum(r[3] for r in rows)
        self.pet.send_msg(
            f"【系统后台强制指令：以下是用户最近{days}天的真实数据统计，请严格基于这些数字，"
            f"用符合你人设的口吻做一段50字以内的简短点评（可以毒舌，但要有建设性，不要编造数据）："
            f"待办完成 {total_done}/{total_all} 个；打卡完成 {cd}/{ca} 次。】",
            hidden=True)
