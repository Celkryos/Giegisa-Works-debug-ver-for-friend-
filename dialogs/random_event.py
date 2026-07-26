from .common import *

class RandomEventDialog(QDialog):
    def __init__(self, parent_pet, event_data):
        super().__init__(parent_pet)
        self.pet = parent_pet
        self.event_data = event_data
        self.setWindowTitle("✨ 随机遭遇事件！")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        self.setMinimumSize(300, 120)
        self.layout = QVBoxLayout(self)

        lbl = QLabel(f"<b>【突发情景】</b><br>{event_data.get('scenario', '')}")
        lbl.setWordWrap(True)
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.layout.addWidget(lbl)
        
        btn_layout = QHBoxLayout()
        btn_a = QPushButton(event_data.get('optA', '选项A'))
        btn_a.setStyleSheet("padding: 8px; background-color: #2196F3; color: white;")
        btn_a.clicked.connect(lambda checked=False: self.make_choice('A'))
        
        btn_b = QPushButton(event_data.get('optB', '选项B'))
        btn_b.setStyleSheet("padding: 8px; background-color: #FF9800; color: white;")
        btn_b.clicked.connect(lambda checked=False: self.make_choice('B'))
        
        btn_layout.addWidget(btn_a)
        btn_layout.addWidget(btn_b)
        self.layout.addLayout(btn_layout)

    def showEvent(self, event):
        super().showEvent(event)
        self.adjustSize()
        if self.width() > 500:
            self.resize(500, self.height())
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                max(geo.left(), min(self.x(), geo.right() - self.width() + 1)),
                max(geo.top(), min(self.y(), geo.bottom() - self.height() + 1)))

    def make_choice(self, choice):
        res_text = str(self.event_data.get(f'res{choice}_text', ''))
        coin_change = int(self.event_data.get(f'res{choice}_coin', 0))
        mood_change = int(self.event_data.get(f'res{choice}_mood', 0))
        
        self.pet.config["coins"] = max(0, self.pet.config.get("coins", 0) + coin_change)
        self.pet.change_mood(mood_change)
        save_config(self.pet.config)
        
        if hasattr(self.pet, 'dlg_StoreDialog') and getattr(self.pet, 'dlg_StoreDialog'):
            try:
                self.pet.dlg_StoreDialog.coin_label.setText(f"<h2>💰 当前资产：{self.pet.config['coins']} 数据碎片</h2>")
            except Exception:
                pass
                
        if hasattr(self.pet, 'dlg_MoodDialog') and getattr(self.pet, 'dlg_MoodDialog'):
            try:
                self.pet.dlg_MoodDialog.update_display()
            except Exception:
                pass
                
        self.pet.inject_system_event(
            f"系统：随机剧场事件『{str(self.event_data.get('scenario','')).strip()}』中，用户选择了 [{self.event_data.get('opt'+choice, '')}]", 
            f"【normal】{res_text} (数据碎片变动：{coin_change:+d}，好感变动：{mood_change:+d})"
        )
        self.accept()
