"""电子书删除残留回归测试（纯文件系统，不需要 Qt）。

对应实测反馈：删除 PDF 后目录以 <id>.deleted.<ts> 形式残留，
重启后重试也不消失——根因是 shutil.copy2 把只读属性带进书库，
Windows 上 rmtree 不能删只读文件（WinError 5）。
"""
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dialogs.ebook as ebook_dialog


def _make_readonly_file(path, content=b"x"):
    path.write_bytes(content)
    os.chmod(path, stat.S_IREAD)
    return path


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # ---- 1. 只读文件也能被 _force_delete_dir 删除（核心修复）----
        target = root / "1785073854246003.deleted.1785207988"
        (target / "assets").mkdir(parents=True)
        _make_readonly_file(target / "book.pdf", b"%PDF fake")
        _make_readonly_file(target / "assets" / "page_1_img_1.png")
        ebook_dialog._force_delete_dir(str(target))
        assert not target.exists(), "只读文件目录未能删除"

        # ---- 2. 导入副本不再携带只读属性 ----
        src = _make_readonly_file(root / "source.pdf", b"%PDF fake")
        dst = root / "copy.pdf"
        ebook_dialog._copy_book_file(str(src), str(dst))
        assert dst.read_bytes() == b"%PDF fake"
        assert os.access(dst, os.W_OK), "副本仍是只读"

        # ---- 3. 孤儿目录清扫：活书保留、孤儿删除、杂项不动 ----
        old_dir = ebook_dialog.EBOOK_DIR
        ebook_dialog.EBOOK_DIR = str(root / "library")
        library = Path(ebook_dialog.EBOOK_DIR)
        live = library / "1001"
        orphan = library / "2002"
        misc = library / "我的资料"
        deleted = library / "3003.deleted.1785207988"
        for folder in (live, orphan, misc, deleted):
            folder.mkdir(parents=True)
        (live / "book.epub").write_bytes(b"epub")
        (orphan / "assets").mkdir()
        _make_readonly_file(orphan / "assets" / "img.png")
        (misc / "笔记.txt").write_text("用户自己的文件", encoding="utf-8")
        _make_readonly_file(deleted / "book.pdf", b"%PDF fake")

        library_config = [{"id": "1001", "title": "活书"}]
        # 配置异常（LOAD_WARNINGS 非空）时绝不清扫
        old_warnings = ebook_dialog.LOAD_WARNINGS
        ebook_dialog.LOAD_WARNINGS = ["模拟配置恢复"]
        ebook_dialog._sweep_orphan_book_dirs([])
        assert orphan.exists(), "LOAD_WARNINGS 非空时不应清扫"
        ebook_dialog.LOAD_WARNINGS = old_warnings
        # 正常清扫
        ebook_dialog._sweep_orphan_book_dirs(library_config)
        assert live.exists(), "活书目录被误删"
        assert not orphan.exists(), "孤儿目录未清理"
        assert misc.exists(), "用户杂项目录被误删"
        assert deleted.exists(), ".deleted. 目录应留给阶段2处理"

        # ---- 4. 启动清理端到端：.deleted. 残留（含只读文件）被移除 ----
        ebook_dialog._cleanup_pending_ebook_deletions(library_config)
        assert not deleted.exists(), ".deleted. 残留重启后仍未清除"
        assert live.exists() and misc.exists()

        ebook_dialog.EBOOK_DIR = old_dir
    print("EBOOK_CLEANUP_OK")


if __name__ == "__main__":
    main()
