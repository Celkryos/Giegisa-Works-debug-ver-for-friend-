"""???????????????"""

from .common import *

class EditNoteDialog(QDialog):
    """【新增】便签热编辑面板"""
    def __init__(self, pet, note):
        super().__init__(pet)
        self.pet = pet
        self.note = note
        self.setWindowTitle("✏️ 编辑便签")
        self.resize(400, 300)
        self.layout = QVBoxLayout(self)
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(note.get("text", ""))
        self.layout.addWidget(self.text_edit)
        
        btn = QPushButton("💾 保存修改")
        btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; font-weight: bold;")
        btn.clicked.connect(self.save_edit)
        self.layout.addWidget(btn)
        
    def save_edit(self):
        self.note["text"] = self.text_edit.toPlainText().strip()
        self.accept()
        QTimer.singleShot(
            0, lambda pet=self.pet: (
                save_config(pet.config),
                pet.refresh_dialogs("dlg_NotesManagerDialog")))

class QuickNoteDialog(QDialog):
    def __init__(self, parent_pet):
        super().__init__(parent_pet)
        self.pet = parent_pet
        self.setWindowTitle("📝 随手记 (便签)")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowOpacity(0.92) 
        self.resize(300, 160)
        self.layout = QVBoxLayout(self)
        
        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText("随时记录一闪而过的灵感或笔记...")
        self.layout.addWidget(self.input_box)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("💾 记录")
        save_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        save_btn.clicked.connect(self.save_note)
        
        mgr_btn = QPushButton("🗂️ 管理便签")
        mgr_btn.clicked.connect(lambda checked=False: self.pet.open_dialog(NotesManagerDialog))
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(mgr_btn)
        self.layout.addLayout(btn_layout)

    def save_note(self):
        text = self.input_box.toPlainText().strip()
        if not text: return
        
        txt_path = os.path.join(BASE_DIR, "notes.txt")
        # notes.txt 只是方便人直接阅读的额外备份；即使目录只读或磁盘暂时
        # 不可写，也不能影响便签本身保存到 config.json。
        try:
            with open(txt_path, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except Exception as e:
            print(f"[便签文本备份写入失败] {e}")
            
        self.pet.config.setdefault("notes", []).append({
            "id": new_id(), 
            "time": datetime.now().strftime('%Y-%m-%d %H:%M'),
            "text": text, 
            "status": "active", 
            "folder": "默认便签", 
            "pinned": False, 
            "locked": False
        })
        self.input_box.clear()
        self.accept()
        QTimer.singleShot(
            0, lambda pet=self.pet: (
                save_config(pet.config),
                pet.inject_system_event(
                    "系统：用户记录了一条便签",
                    "【normal】已将你的杂念转录至底层存储区。"),
                pet.refresh_dialogs("dlg_NotesManagerDialog")))

class NotesManagerDialog(QDialog):
    """【重构】带有分组、置顶、排序的终极便签管理器"""
    def __init__(self, parent_pet):
        super().__init__(parent_pet)
        self.pet = parent_pet
        self.setWindowTitle("🗂️ 便签管理与归档")
        self.setMinimumSize(520, 380)
        self.resize(720, 480)
        self.layout = QVBoxLayout(self)
        self.current_folder = "默认便签"
        
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("📂 分组:"))
        
        self.folder_combo = QComboBox()
        self.folder_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.update_folder_combo()
        self.folder_combo.currentIndexChanged.connect(self.on_folder_change)
        folder_layout.addWidget(self.folder_combo, stretch=1)

        folder_layout.addWidget(QLabel("↕️ 排序:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["最新创建优先", "最早创建优先"])
        self.sort_combo.currentIndexChanged.connect(self.refresh_list)
        folder_layout.addWidget(self.sort_combo)
        self.layout.addLayout(folder_layout)

        folder_actions = QHBoxLayout()
        
        btn_new_folder = QPushButton("➕新建分组")
        btn_new_folder.clicked.connect(self.new_folder)
        folder_actions.addWidget(btn_new_folder)
        
        btn_rename_folder = QPushButton("✏️重命名")
        btn_rename_folder.clicked.connect(self.rename_folder)
        folder_actions.addWidget(btn_rename_folder)
        
        btn_del_folder = QPushButton("❌删除当前分组")
        btn_del_folder.setStyleSheet("color: red;")
        btn_del_folder.clicked.connect(self.delete_folder)
        folder_actions.addWidget(btn_del_folder)
        folder_actions.addStretch()
        self.layout.addLayout(folder_actions)
        
        self.list_widget = ResponsiveListWidget()
        self.layout.addWidget(self.list_widget)
        
        btn_layout = QHBoxLayout()
        self.export_btn = QPushButton("💾 导出当前分组")
        self.export_btn.clicked.connect(self.export_notes)
        
        self.import_btn = QPushButton("📂 导入至当前分组")
        self.import_btn.clicked.connect(self.import_notes)
        
        btn_layout.addWidget(self.export_btn)
        btn_layout.addWidget(self.import_btn)
        self.layout.addLayout(btn_layout)
        
        self.refresh_list()

    def update_folder_combo(self):
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        folders = self.pet.config.setdefault("note_folders", ["默认便签"])
        if "默认便签" not in folders:
            folders.insert(0, "默认便签")
        self.folder_combo.addItems(folders)
        self.folder_combo.setCurrentText(self.current_folder)
        self.folder_combo.blockSignals(False)

    def on_folder_change(self):
        self.current_folder = self.folder_combo.currentText()
        self.refresh_list()

    def new_folder(self):
        dlg = InputDialog("新建便签分组", "请输入分组名称:", self)
        if dlg.exec():
            text = dlg.get_text()
            if text and text not in self.pet.config["note_folders"]:
                self.pet.config["note_folders"].append(text)
                save_config(self.pet.config)
                self.update_folder_combo()
                self.folder_combo.setCurrentText(text)

    def delete_folder(self):
        """删除便签分组并将内部便签转移至默认区域"""
        if self.current_folder == "默认便签":
            QMessageBox.warning(self, "禁止操作", "【默认便签】为系统基础分组，无法被删除！")
            return
            
        reply = QMessageBox.question(self, '确认删除', f'确定要删除分组【{self.current_folder}】吗？\n为防止数据丢失，该分组下的所有便签将被安全转移至【默认便签】！', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            # 1. 遍历并转移该分类下的便签
            for note in self.pet.config.get("notes", []):
                if note.get("folder") == self.current_folder:
                    note["folder"] = "默认便签"
                    
            # 2. 删除文件夹记录
            if self.current_folder in self.pet.config.get("note_folders", []):
                self.pet.config["note_folders"].remove(self.current_folder)
                
            save_config(self.pet.config)
            self.current_folder = "默认便签"
            self.update_folder_combo()
            self.refresh_list()
            QMessageBox.information(self, "成功", "分组已删除，内部便签已转移至【默认便签】。")

    def rename_folder(self):
        if self.current_folder == "默认便签":
            QMessageBox.warning(self, "禁止操作", "【默认便签】为系统基础兼全局分组，无法重命名！")
            return
            
        dlg = InputDialog("重命名分组", f"将【{self.current_folder}】重命名为:", self)
        dlg.input.setText(self.current_folder)
        if dlg.exec():
            new_name = dlg.get_text()
            if new_name and new_name != self.current_folder:
                if new_name in self.pet.config["note_folders"]:
                    QMessageBox.warning(self, "错误", "该分组名称已存在！")
                    return
                # 同步修改所有相关便签
                for n in self.pet.config.get("notes", []):
                    if n.get("folder") == self.current_folder:
                        n["folder"] = new_name
                # 修改目录名单
                idx = self.pet.config["note_folders"].index(self.current_folder)
                self.pet.config["note_folders"][idx] = new_name
                save_config(self.pet.config)
                
                self.current_folder = new_name
                self.update_folder_combo()
                self.refresh_list()
                QMessageBox.information(self, "成功", "重命名成功！")

    def refresh_list(self):
        self.list_widget.clear()
        all_notes = self.pet.config.get("notes", [])
        filtered_notes = []
        
        # 兼容旧版本数据并过滤
        for n in all_notes:
            if "folder" not in n: n["folder"] = "默认便签"
            if "pinned" not in n: n["pinned"] = False
            if "locked" not in n: n["locked"] = False
            if "status" not in n: n["status"] = "active"
            
            # 如果选择的是“默认便签”，则显示所有便签；否则只显示对应文件夹的
            if (self.current_folder == "默认便签" or n["folder"] == self.current_folder) and n["status"] != "hidden": 
                filtered_notes.append(n)
                
        is_desc = (self.sort_combo.currentIndex() == 0)
        filtered_notes.sort(key=lambda x: x.get("time", ""), reverse=is_desc)
        filtered_notes.sort(key=lambda x: x.get("pinned", False), reverse=True) 

        for note in filtered_notes:
            item_widget = QWidget()
            item_layout = QVBoxLayout(item_widget)
            item_layout.setContentsMargins(6, 4, 6, 4)
            item_layout.setSpacing(4)
            
            pin_icon = "📌" if note["pinned"] else "📝"
            lbl = QLabel(f"[{note.get('time', '')}] {pin_icon}\n{note.get('text', '')}")
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            item_layout.addWidget(lbl)
            
            locked = note["locked"]
            button_grid = QGridLayout()
            button_grid.setContentsMargins(0, 0, 0, 0)
            button_grid.setHorizontalSpacing(4)
            button_grid.setVerticalSpacing(3)
            
            btn_edit = QPushButton("✏️编辑")
            btn_edit.setEnabled(not locked)
            btn_edit.clicked.connect(lambda checked=False, n=note: self.open_editor(n))
            
            btn_pin = QPushButton("❌取消置顶" if note["pinned"] else "📌置顶")
            btn_pin.clicked.connect(lambda checked=False, n=note: self.toggle_pin(n))
            
            btn_lock = QPushButton("🔓解锁" if locked else "🔒锁定")
            btn_lock.clicked.connect(lambda checked=False, n=note: self.toggle_lock(n))
            
            btn_move = QPushButton("📂移动")
            btn_move.setEnabled(not locked)
            btn_move.clicked.connect(lambda checked=False, n=note: self.move_note(n))
            
            btn_del = QPushButton("❌删除")
            btn_del.setEnabled(not locked)
            btn_del.clicked.connect(lambda checked=False, n=note: self.del_note(n))
            
            for col, button in enumerate((btn_edit, btn_pin, btn_lock)):
                button.setMinimumHeight(34)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                button_grid.addWidget(button, 0, col)
            for col, button in enumerate((btn_move, btn_del)):
                button.setMinimumHeight(34)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                button_grid.addWidget(button, 1, col)
            item_layout.addLayout(button_grid)
            item_widget.setMinimumHeight(max(118, item_widget.sizeHint().height()))
            
            item = QListWidgetItem()
            item.setSizeHint(item_widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, item_widget)

    def open_editor(self, note):
        dlg = EditNoteDialog(self.pet, note)
        if dlg.exec(): 
            self.refresh_list()

    def toggle_pin(self, note):
        note["pinned"] = not note.get("pinned", False)
        save_config(self.pet.config)
        self.refresh_list()

    def toggle_lock(self, note):
        note["locked"] = not note.get("locked", False)
        save_config(self.pet.config)
        self.refresh_list()

    # 找到整个 move_note 方法，替换为：
    def move_note(self, note):
        folders = self.pet.config.setdefault("note_folders", ["默认便签"])
        folder_name, ok = QInputDialog.getItem(self, "移动便签", "请选择目标分组:", folders, 0, False)
        
        if ok and folder_name:
            note["folder"] = folder_name
            save_config(self.pet.config)
            self.refresh_list()
            QMessageBox.information(self, "成功", f"已移动至分组：{folder_name}")

    def del_note(self, note):
        self.pet.config["notes"].remove(note)
        save_config(self.pet.config)
        self.refresh_list()

    def export_notes(self):
        path, _ = QFileDialog.getSaveFileName(self, f"导出分组 {self.current_folder}", BASE_DIR, "JSON Files (*.json)")
        if path:
            try:
                data = [n for n in self.pet.config.get("notes", []) if n.get("folder", "默认便签") == self.current_folder]
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                QMessageBox.information(self, "成功", "导出成功！")
            except Exception as e:
                QMessageBox.critical(self, "失败", f"导出失败：{str(e)}")

    def import_notes(self):
        path, _ = QFileDialog.getOpenFileName(self, f"导入至 {self.current_folder}", BASE_DIR, "JSON Files (*.json)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    QMessageBox.warning(self, "错误", "格式不正确：文件内容应该是一个列表。")
                    return
                good = []
                for d in data:
                    if not isinstance(d, dict) or "text" not in d:
                        continue
                    item = dict(d)
                    item["folder"] = self.current_folder
                    item["id"] = new_id()
                    item.setdefault("status", "active")
                    item.setdefault("pinned", False)
                    item.setdefault("locked", False)
                    good.append(item)
                if not good:
                    QMessageBox.warning(self, "错误", "文件里没有可识别的便签记录。")
                    return
                self.pet.config.setdefault("notes", []).extend(good)
                save_config(self.pet.config)
                self.refresh_list()
                QMessageBox.information(
                    self, "成功",
                    f"成功导入 {len(good)} 条便签；格式不正确的条目已跳过。")
            except Exception as e:
                QMessageBox.critical(self, "失败", f"导入失败：{str(e)}")
