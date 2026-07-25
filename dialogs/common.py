"""???????? Qt?????????"""

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

