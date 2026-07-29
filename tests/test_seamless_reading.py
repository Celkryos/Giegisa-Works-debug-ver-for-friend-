"""电子书无缝翻页（滚动连续阅读）回归测试。

覆盖：开关切换、向后自动接续、位置同步、顶部裁剪有界、向上补页、
批注修改后整页重绘、关闭后恢复逐页模式。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QWidget

import oc
from dialogs.ebook import EbookReaderDialog


class FakePet(QWidget):
    def __init__(self):
        super().__init__()
        self.config = json.loads(json.dumps(oc.DEFAULT_CONFIG))
        self.events = []
        self.calendar_service = oc.CalendarService(self.config)

    def inject_system_event(self, *args):
        self.events.append(args)

    def show_bubble(self, *args, **kwargs):
        pass

    def send_msg(self, *args, **kwargs):
        pass

    def open_dialog(self, *args):
        pass


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    old_saver = oc.save_config
    import dialogs.ebook as ebook_dialog
    old_dialog_saver = ebook_dialog.save_config
    oc.save_config = lambda *args, **kwargs: True
    ebook_dialog.save_config = lambda *args, **kwargs: True
    with tempfile.TemporaryDirectory() as tmp:
        txt = Path(tmp) / "book.txt"
        body = "".join(
            f"第{chapter}章\n" + "这一章的内容很长，足够分出很多页来测试无缝接续。" * 30 + "\n\n"
            for chapter in "一二三四五六七八九十")
        txt.write_bytes(body.encode("gb18030"))
        book = {
            "id": "seamless-book", "title": "无缝测试书", "path": str(txt),
            "asset_dir": str(Path(tmp) / "assets"), "managed": False,
            "category": "测试", "status": "未读", "progress": 0,
            "position": 0, "bookmarks": [], "annotations": []}
        pet = FakePet()
        reader = EbookReaderDialog(pet, book)
        reader.show()
        app.processEvents()
        assert len(reader.pages) >= 6, f"页数太少，无法测试: {len(reader.pages)}"

        bar = reader.text.verticalScrollBar()

        # ---- 1. 开启无缝：文档 = 当前页 + 预取页 ----
        reader._set_setting("seamless_reading", True)
        app.processEvents()
        assert reader._seamless_enabled()
        doc_len = len(reader.text.toPlainText())
        page_len = reader.pages[0][1] - reader.pages[0][0]
        assert doc_len > page_len, "开启后文档应包含预取的下一页"
        assert reader._seamless_next_index >= 1

        # ---- 2. 滚到底部：自动接续下一页 ----
        before_index = reader._seamless_next_index
        before_len = len(reader.text.toPlainText())
        bar.setValue(bar.maximum())
        app.processEvents()
        assert reader._seamless_next_index > before_index, "滚到底部没有接续"
        assert len(reader.text.toPlainText()) > before_len
        assert reader._seamless_end == reader.pages[reader._seamless_next_index - 1][1]

        # ---- 3. 连续接续触发顶部裁剪（文档规模有界）----
        reader._seamless_max_pages = 3
        for _ in range(6):
            bar.setValue(bar.maximum())
            app.processEvents()
        retained = reader._seamless_next_index - reader._seamless_base_index
        assert retained <= 3, f"裁剪后保留页数 {retained} 超限"
        assert reader._seamless_base == reader.pages[reader._seamless_base_index][0]
        assert reader._seamless_base_index > 0, "顶部没有被裁剪"

        # ---- 4. 位置同步：当前页随滚动更新并写回 book.position ----
        reader._seamless_sync_position()
        top_abs = reader._seamless_base + reader.text.cursorForPosition(
            reader.text.viewport().rect().topLeft()).position()
        assert reader.pages[reader.current_page][0] <= top_abs < reader.pages[reader.current_page][1]
        assert book["position"] == reader.pages[reader.current_page][0]

        # ---- 5. 滚回顶部：自动补回上一页且视口内容稳定 ----
        old_base_index = reader._seamless_base_index
        bar.setValue(0)
        app.processEvents()
        assert reader._seamless_base_index < old_base_index, "滚到顶部没有补回前文"
        assert reader._seamless_base == reader.pages[reader._seamless_base_index][0]

        # ---- 6. 批注修改：无缝模式下整页重绘不丢文本 ----
        mark = {"id": "m1", "type": "highlight", "start": reader._seamless_base + 5,
                "end": reader._seamless_base + 20, "text": "t", "color": "#fecaca",
                "note": "", "created": "2026-07-28T00:00"}
        book["annotations"].append(mark)
        reader._refresh_marks_view()
        app.processEvents()
        doc_text = reader.text.toPlainText()
        assert doc_text[:20] == reader.full_text[reader._seamless_base:reader._seamless_base + 20]
        book["annotations"].clear()
        reader._refresh_marks_view()
        app.processEvents()

        # ---- 7. 关闭无缝：恢复逐页单页文档 ----
        reader._set_setting("seamless_reading", False)
        app.processEvents()
        single = len(reader.text.toPlainText())
        s, e, _ = reader.pages[reader.current_page]
        assert single == e - s, (single, e - s)

        reader.session_timer.stop()
        reader.close()
        reader.deleteLater()
        app.processEvents()
    oc.save_config = old_saver
    ebook_dialog.save_config = old_dialog_saver
    print("SEAMLESS_READING_OK")


if __name__ == "__main__":
    main()
