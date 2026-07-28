import hashlib
import inspect
import pathlib
import sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
import oc
from api.openai_compat import _join_url
EXPECTED_PROMPT_SHA256 = "77a11d0a49504c865b8b49dd120ef9bdf1479dc194dba7d7678ec3a1c8201b83"
EXPECTED_CLASSES = ['ApiSettingsDialog', 'AppearanceDialog', 'AutoEventSettingsDialog', 'ChatInputBox', 'ChatThread', 'CheckinAlertDialog', 'CheckinDialog', 'CollectionManagerDialog', 'DataRetrievalThread', 'DayDetailDialog', 'DesktopPet', 'DistractionSettingsDialog', 'DraggableListWidget', 'EditCheckinDialog', 'EditNoteDialog', 'EditScheduleDialog', 'FocusDialog', 'FocusOverlay', 'HistoryDialog', 'IdleChatThread', 'ImageBubble', 'ImageFetchThread', 'InputDialog', 'ItemRetrievalThread', 'MemorySettingsDialog', 'MiniCalendarDialog', 'MoodDialog', 'NotesManagerDialog', 'QuickNoteDialog', 'RandomEventDialog', 'RandomEventThread', 'ResponsiveListWidget', 'ScheduleAlertDialog', 'ScheduleDialog', 'StatsDialog', 'StoreDialog', 'TriviaThread', 'UserProfileDialog']
def main():
    actual = hashlib.sha256(config.DEFAULT_CONFIG["system_prompt"].encode("utf-8")).hexdigest()
    assert actual == EXPECTED_PROMPT_SHA256
    assert config.DEFAULT_CONFIG["gemini_model_name"] == "gemini-3.5-flash"
    assert config.DEFAULT_CONFIG["bubble_border"] == "#0cd6ff"
    assert oc.sanitize_bubble_text("(normal) 正文") == "正文"
    assert oc.sanitize_bubble_text("【shy】正文") == "正文"
    assert "后台状态干预" not in oc.sanitize_bubble_text(
        "[后台状态干预：这段不能显示]正文")
    assert _join_url("https://api.siliconflow.cn/v1") == "https://api.siliconflow.cn/v1"
    assert _join_url("https://api.x.com/v1/chat/completions") == "https://api.x.com/v1"
    for name in EXPECTED_CLASSES:
        assert hasattr(oc, name), name
    init_source = inspect.getsource(oc.DesktopPet.__init__)
    assert "HTTP_PROXY" not in init_source
    assert "HTTPS_PROXY" not in init_source
    menu_source = inspect.getsource(oc.DesktopPet._build_context_menu)
    assert menu_source.index("传达者日程系统") < menu_source.index("cal_menu = QMenu")
    assert menu_source.index("cal_menu = QMenu") < menu_source.index("静默阅读舱")
    # Existing user data must remain loadable on every launch.
    assert isinstance(config.load_config(), dict)
    print("REFACTOR_CONTRACT_OK")
if __name__ == "__main__":
    main()
