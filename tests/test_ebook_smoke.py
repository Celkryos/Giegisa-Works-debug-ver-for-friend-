import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPoint, QTimer
from PyQt6.QtGui import QImage, QTextCursor
from PyQt6.QtWidgets import QApplication, QWidget

import oc
from core.ebook import IMAGE_OBJECT, parse_ebook
from dialogs.ebook import EbookReaderDialog, EbookShelfDialog


class FakePet(QWidget):
    def __init__(self):
        super().__init__()
        self.config = json.loads(json.dumps(oc.DEFAULT_CONFIG))
        self.events = []
        self.bubbles = []
        self.messages = []

    def inject_system_event(self, *args):
        self.events.append(args)

    def show_bubble(self, text, **kwargs):
        self.bubbles.append(text)

    def send_msg(self, text, **kwargs):
        self.messages.append(text)

    def do_checkin(self, item, d=None, done=True, quiet=False):
        oc.checkin_set_done(item, d, done)

    def open_dialog(self, *args):
        pass


def make_epub(path):
    container = """<?xml version="1.0"?>
    <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
      <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
    </container>"""
    opf = """<package xmlns="http://www.idpf.org/2007/opf">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>测试 EPUB</dc:title></metadata>
      <manifest><item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>
      <item id="pic" href="pic.png" media-type="image/png"/></manifest>
      <spine><itemref idref="c1"/></spine></package>"""
    chapter = """<html><body><h1>第一章</h1><p>这是 EPUB 正文。</p><img src="pic.png"/></body></html>"""
    png = Path(oc.UI_BACKGROUND_FILE).read_bytes()
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/chapter.xhtml", chapter)
        zf.writestr("OEBPS/pic.png", png)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    old_saver = oc.save_config
    import dialogs.ebook as ebook_dialog
    old_dialog_saver = ebook_dialog.save_config
    oc.save_config = lambda *args, **kwargs: True
    ebook_dialog.save_config = lambda *args, **kwargs: True
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        txt = tmp_path / "book.txt"
        txt.write_bytes("第一章\n这是被记事本\n切断的句子。\n\n第二章\n下一章。".encode("gb18030"))
        html_path = tmp_path / "book.html"
        html_path.write_text("<h1>HTML 标题</h1><p>正文一。</p><p>正文二。</p>", encoding="utf-8")
        epub_path = tmp_path / "book.epub"
        make_epub(epub_path)
        pdf_path = tmp_path / "book.pdf"
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "PDF test page")
        doc.save(pdf_path)
        doc.close()

        parsed_txt = parse_ebook(str(txt), str(tmp_path / "txt_assets"))
        assert "被记事本切断" in parsed_txt["chapters"][0]["text"]
        assert len(parsed_txt["chapters"]) == 2
        parsed_html = parse_ebook(str(html_path), str(tmp_path / "html_assets"))
        assert parsed_html["title"] == "HTML 标题"
        parsed_epub = parse_ebook(str(epub_path), str(tmp_path / "epub_assets"))
        assert parsed_epub["title"] == "测试 EPUB"
        assert parsed_epub["chapters"][0]["images"]
        assert IMAGE_OBJECT in parsed_epub["chapters"][0]["text"]
        parsed_pdf = parse_ebook(str(pdf_path), str(tmp_path / "pdf_assets"))
        assert "PDF test page" in parsed_pdf["chapters"][0]["text"]

        pet = FakePet()
        pet.config["ebook_settings"]["daily_goal_minutes"] = 1
        book = {
            "id": "test-book", "title": "测试书", "path": str(txt),
            "asset_dir": str(tmp_path / "reader_assets"), "managed": False,
            "category": "测试", "status": "未读", "progress": 0,
            "position": 0, "bookmarks": [], "annotations": []}
        pet.config["ebook_library"] = [book]
        reader = EbookReaderDialog(pet, book)
        reader.show()
        app.processEvents()
        reader.session_timer.stop()
        assert reader.reading_surface.layout().currentWidget() is reader.text
        assert reader.width() >= 500 and reader.height() >= 700
        assert len(reader.pages) >= 1
        assert reader.toc_list.count() == 2
        reading_checkin = next(
            item for item in pet.config["checkins"]
            if item.get("id") == "ebook_daily_reading")
        today = str(__import__("datetime").date.today())
        pet.config["ebook_reading_daily"][today] = {
            "seconds": 59, "chars": 0, "reward_units": 0, "goal_awarded": False}
        bubble_count = len(pet.bubbles)
        reader._show_open_notice()
        assert len(pet.bubbles) == bubble_count
        reader._reading_second()
        assert oc.checkin_done_on(reading_checkin, __import__("datetime").date.today())
        assert "每天仅首次" in pet.events[-1][1]
        assert "5 数据碎片" in pet.events[-1][1]
        goal_event_count = len(pet.events)
        for _ in range(600):
            reader._reading_second()
        assert len(pet.events) == goal_event_count
        reader.toggle_panel(2)
        app.processEvents()
        assert reader.panel.isVisible()
        assert reader.width() >= (
            reader.PANEL_WIDTH + reader.READING_MIN_WIDTH + 70)
        assert reader.stack.currentWidget().horizontalScrollBar().maximum() == 0
        reader.toggle_panel(2)
        reader.add_bookmark()
        assert len(book["bookmarks"]) == 1
        cursor = reader.text.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(min(4, len(reader.text.toPlainText())), QTextCursor.MoveMode.KeepAnchor)
        reader.text.setTextCursor(cursor)
        reader.highlight_selection()
        assert len(book["annotations"]) == 1
        assert book["annotations"][0]["color"] == reader.settings["highlight_color"]
        # The same sentence is one logical highlight, even when highlighted again.
        reader.settings["highlight_color"] = "#c4b5fd"
        duplicate_cursor = reader.text.textCursor()
        duplicate_cursor.setPosition(0)
        duplicate_cursor.setPosition(
            min(4, len(reader.text.toPlainText())),
            QTextCursor.MoveMode.KeepAnchor)
        reader.text.setTextCursor(duplicate_cursor)
        reader.highlight_selection()
        assert len(book["annotations"]) == 1
        assert book["annotations"][0]["color"] == "#c4b5fd"
        assert hasattr(reader, "change_mark_color")
        outside = QTextCursor(reader.text.document())
        outside.setPosition(min(8, max(0, len(reader.text.toPlainText()) - 1)))
        assert outside.charFormat().background().color().alpha() == 0
        reader.search_input.setText("句子")
        reader.search_text()
        assert reader.search_results.count() >= 1
        assert reader.search_results.item(0).text().startswith("1. 第 ")
        reader._set_setting("text_color", "#123456")
        reader._apply_preset(True)
        reader._set_setting("text_color", "#f1f5f9")
        reader._set_setting("font_size", 12, True)
        assert reader.settings["night_mode"]
        assert "background-color: rgba(35, 45, 55" in reader.styleSheet()
        app.processEvents()
        reader.grab().save(str(ROOT / "_smoke_EbookNight.png"))
        reader._apply_preset(False)
        assert reader.settings["text_color"] == "#123456"
        assert reader.settings["font_size"] == 10
        reader._apply_preset(True)
        assert reader.settings["text_color"] == "#f1f5f9"
        assert reader.settings["font_size"] == 12
        reader._apply_preset(False)
        pet.config["openai_api_key"] = "test-key"
        pet.config["openai_model_name"] = "test-model"
        reader.talk_about_selection()
        assert pet.messages and "请结合上下文谈谈" in pet.messages[-1]
        assert "真实调用接口" in reader._ai_status_text()
        reader.settings["background_mode"] = "拉伸"
        reader.settings["background_opacity"] = 20
        rendered_bg = reader._render_background_image(oc.UI_BACKGROUND_FILE)
        rendered_image = QImage(rendered_bg)
        assert not rendered_image.isNull()
        assert rendered_image.size() == reader.text.size()
        center = rendered_image.pixelColor(
            rendered_image.width() // 2, rendered_image.height() // 2)
        assert center.alpha() == 255
        assert center != QImage(oc.UI_BACKGROUND_FILE).pixelColor(
            QImage(oc.UI_BACKGROUND_FILE).width() // 2,
            QImage(oc.UI_BACKGROUND_FILE).height() // 2)
        reader.settings["background_image"] = oc.UI_BACKGROUND_FILE
        reader.settings["background_mode"] = "平铺"
        reader.settings["background_opacity"] = 35
        reader.show_page()
        assert reader.background_label.pixmap() is not None
        assert not reader.background_label.pixmap().isNull()
        reader.toggle_panel(2)
        app.processEvents()
        reader.grab().save(str(ROOT / "_smoke_EbookReader.png"))
        reader.toggle_panel(2)
        reader.auto_speed.setValue(30)
        reader.auto_mode.setCurrentIndex(0)
        reader.start_auto_read()
        for _ in range(10):
            reader._auto_tick()
        assert reader._auto_position > 0
        reader.stop_auto_read()

        # Removing a highlight is also available from the reading surface.
        delete_cursor = reader.text.textCursor()
        delete_cursor.setPosition(0)
        delete_cursor.setPosition(
            min(4, len(reader.text.toPlainText())),
            QTextCursor.MoveMode.KeepAnchor)
        reader.text.setTextCursor(delete_cursor)
        assert reader._highlights_at(QPoint(1, 1))
        reader.remove_highlight_at(QPoint(1, 1))
        assert not book["annotations"]

        # Speech mode must not advance while the current bubble is still typing.
        reader._auto_running = True
        reader._auto_paused = False
        reader._auto_position = 0
        reader._last_page_end = 0
        pet.is_typing = True
        reader._speech_bubble(reader._auto_generation)
        assert reader._auto_position == 0
        pet.is_typing = False
        reader._speech_bubble(reader._auto_generation)
        assert reader._auto_position > 0
        reader.stop_auto_read()
        reader.close()
        reader.deleteLater()
        app.processEvents()

        image_book = {
            "id": "image-book", "title": "图片书", "path": str(epub_path),
            "asset_dir": str(tmp_path / "image_reader_assets"), "managed": False,
            "category": "测试", "status": "未读", "progress": 0,
            "position": 0, "bookmarks": [], "annotations": []}
        pet.config["ebook_library"].append(image_book)
        image_reader = EbookReaderDialog(pet, image_book)
        image_reader.show()
        app.processEvents()
        assert image_reader.inline_images
        image_position = next(iter(image_reader.inline_images))
        assert image_position in image_reader.block_image_positions
        image_reader.goto_position(image_position)
        assert IMAGE_OBJECT in image_reader.text.toPlainText()
        assert image_reader.pages[image_reader.current_page][:2] == (
            image_position, image_position + 1)
        image_reader.grab().save(str(ROOT / "_smoke_EbookImage.png"))
        image_reader.close()
        image_reader.deleteLater()
        app.processEvents()

        shelf = EbookShelfDialog(pet)
        shelf.show()
        app.processEvents()
        assert len(shelf.visible_books) == 2
        assert shelf.width() < shelf.height()
        assert shelf.book_scroll.horizontalScrollBar().maximum() == 0
        managed = shelf._register(str(html_path), managed=True)
        assert managed["managed"] and os.path.isfile(managed["path"])
        managed["bookmarks"] = [{"id": "kept", "position": 1}]
        shelf.refresh_table()
        assert len(shelf.visible_books) == 3
        same_managed = shelf._register(str(html_path), managed=True)
        assert same_managed is managed
        assert len(shelf.books()) == 3
        assert same_managed["bookmarks"][0]["id"] == "kept"
        shelf.grab().save(str(ROOT / "_smoke_EbookShelf.png"))
        shelf.close()
        shelf.deleteLater()

        old_ebook_dir = ebook_dialog.EBOOK_DIR
        portable_dir = tmp_path / "portable_library"
        ebook_dialog.EBOOK_DIR = str(portable_dir)
        portable_folder = portable_dir / "portable-id"
        portable_folder.mkdir(parents=True)
        portable_copy = portable_folder / "book.epub"
        portable_copy.write_bytes(epub_path.read_bytes())
        recovery_pet = FakePet()
        recovery_pet.config["ebook_library"] = [{
            "id": "portable-id", "title": "测试 EPUB",
            "path": "Z:/旧安装/ebook_library/portable-id/book.epub",
            "asset_dir": "Z:/旧安装/ebook_library/portable-id/assets",
            "managed": True, "category": "默认书架", "status": "阅读中",
            "progress": 42.0, "position": 18, "size": epub_path.stat().st_size,
            "bookmarks": [{"id": "old-bookmark", "position": 10}],
            "annotations": [{"id": "old-note", "start": 1, "end": 3}],
        }, {
            "id": "duplicate-id", "title": "测试 EPUB",
            "path": str(epub_path), "asset_dir": str(tmp_path / "dup-assets"),
            "managed": False, "category": "默认书架", "status": "未读",
            "progress": 0, "position": 0, "size": epub_path.stat().st_size,
            "bookmarks": [{"id": "new-bookmark", "position": 20}],
            "annotations": [],
        }]
        recovery_shelf = EbookShelfDialog(recovery_pet)
        assert len(recovery_shelf.books()) == 1
        recovered = recovery_shelf.books()[0]
        assert os.path.isfile(recovered["path"])
        assert recovered["progress"] == 42.0
        assert {mark["id"] for mark in recovered["bookmarks"]} == {
            "old-bookmark", "new-bookmark"}
        restored = recovery_shelf._register(str(epub_path), managed=True)
        assert restored is recovered
        assert len(recovery_shelf.books()) == 1
        assert os.path.isfile(restored["path"])
        recovery_shelf.close()
        recovery_shelf.deleteLater()
        recovery_pet.deleteLater()
        ebook_dialog.EBOOK_DIR = old_ebook_dir
        pet.close()
        pet.deleteLater()
        app.processEvents()
    oc.save_config = old_saver
    ebook_dialog.save_config = old_dialog_saver
    print("EBOOK_SMOKE_OK")


if __name__ == "__main__":
    main()
