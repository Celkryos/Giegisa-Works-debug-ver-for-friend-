import sys
import os
import random
import time
import re
import json
import base64
import urllib.request
import urllib.error
import calendar as _pycalendar
from datetime import datetime, date, timedelta
from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QMenu, QLineEdit, QVBoxLayout, QHBoxLayout, QDialog, QListWidget, QPushButton, QListWidgetItem, QTextEdit, QMessageBox, QFormLayout, QSpinBox, QColorDialog, QComboBox, QGroupBox, QFileDialog, QTimeEdit, QSizePolicy, QInputDialog, QSystemTrayIcon, QCheckBox, QGridLayout, QDateEdit, QScrollArea)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QPoint, QTime, QByteArray, QBuffer, QIODevice, QDate
from PyQt6.QtGui import QPixmap, QColor, QAction, QCursor, QIcon, QImage
from config import BASE_DIR, PIC_DIR, CONFIG_FILE, HISTORY_FILE, NOTES_FILE, DEFAULT_CONFIG, LOAD_WARNINGS, safe_json_save, load_config, save_config, flush_config_if_dirty
from core.utils import *
from ui import MENU_QSS, ImageBubble, ResponsiveListWidget, DraggableListWidget, ChatInputBox, FocusOverlay, InputDialog
from api import gemini_rest_generate, openai_chat
from threads import ChatThread, TriviaThread, IdleChatThread, RandomEventThread, DataRetrievalThread, ItemRetrievalThread, ImageFetchThread


# ============================================================
#  安全的模态弹窗封装
#  QMessageBox / QInputDialog 作为子窗口弹出时，在 Windows 上
#  有概率被父对话框遮挡（尤其当父窗口为非模态 Tool 窗口时）。
#  以下函数使用 setWindowFlag（追加而非替换）添加
#  WindowStaysOnTopHint，并在 exec 前强制 raise/activateWindow。
#  由于窗口在 exec() 返回后即销毁，StayOnTop 仅存在于弹窗
#  存活期间，不会持久影响父窗口或全局窗口层级。
# ============================================================

def _prepare_modal(box):
    """为模态弹窗追加置顶并提升 z-order。setWindowFlag 是追加模式，
    不会覆盖默认的关闭按钮、系统菜单等窗口行为。"""
    box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    box.show()
    box.raise_()
    box.activateWindow()


def question_box(parent, title, text,
                 buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No):
    """QMessageBox.question 的安全替代——始终在父窗口上方，不被遮挡。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    _prepare_modal(box)
    return box.exec()


def info_box(parent, title, text):
    """QMessageBox.information 的安全替代。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    _prepare_modal(box)
    return box.exec()


def warning_box(parent, title, text):
    """QMessageBox.warning 的安全替代。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    _prepare_modal(box)
    return box.exec()


def critical_box(parent, title, text):
    """QMessageBox.critical 的安全替代。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    _prepare_modal(box)
    return box.exec()


def input_text_box(parent, title, label, text=''):
    """QInputDialog.getText 的安全替代。"""
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextValue(text)
    dlg.setInputMode(QInputDialog.InputMode.TextInput)
    _prepare_modal(dlg)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.textValue(), True
    return '', False


def input_item_box(parent, title, label, items, current=0, editable=False):
    """QInputDialog.getItem 的安全替代。"""
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setComboBoxItems(items)
    dlg.setComboBoxEditable(editable)
    if 0 <= current < len(items):
        dlg.setCurrentIndex(current)
    _prepare_modal(dlg)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.textValue(), True
    return '', False


def input_multi_text_box(parent, title, label, text=''):
    """QInputDialog.getMultiLineText 的安全替代。"""
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextValue(text)
    dlg.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput, True)
    _prepare_modal(dlg)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.textValue(), True
    return '', False
