"""电子书格式识别、文本清理与章节提取。"""

import html
import json
import os
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

SUPPORTED_EBOOKS = {".txt", ".html", ".htm", ".epub", ".pdf"}
PARSER_VERSION = 3
IMAGE_OBJECT = "\ufffc"


def decode_bytes(data):
    if data.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        for encoding in ("utf-8-sig", "utf-16"):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError:
                pass
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    candidates = []
    common = set("的一是了我不在人有这中大来上个国到说们为子和你地出道也时年得就那要下以生会自着去之过家学对可里后小心多天而能好都然没日于起还发成事只作当想看文无开手用主行方又如前所本见经头面公同已老从动两长知民样现分将外但身些与高意进把法此章节")

    def score(text):
        cjk = sum("\u4e00" <= char <= "\u9fff" for char in text)
        familiar = sum(char in common for char in text)
        controls = sum(ord(char) < 32 and char not in "\n\r\t" for char in text)
        return cjk + familiar * 3 - controls * 20

    for encoding in ("gb18030", "big5", "utf-16"):
        try:
            text = data.decode(encoding)
            candidates.append((score(text), text, encoding))
        except (UnicodeDecodeError, LookupError):
            pass
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(data).best()
        if best is not None:
            text = str(best)
            candidates.append((score(text), text, best.encoding or "auto"))
    except Exception:
        pass
    if candidates:
        _, text, encoding = max(candidates, key=lambda item: item[0])
        return text, encoding
    return data.decode("utf-8", errors="replace"), "utf-8/replace"


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.images = []
        self.title = ""
        self._heading = None
        self._heading_parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("head", "style", "script", "noscript"):
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in ("p", "div", "br", "li", "tr"):
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3", "h4"):
            self.parts.append("\n")
            self._heading = tag
            self._heading_parts = []
        if tag == "img" and attrs.get("src"):
            self.images.append(attrs["src"])
            self.parts.append(IMAGE_OBJECT)
        if tag == "image":
            image_ref = attrs.get("href") or attrs.get("xlink:href")
            if image_ref:
                self.images.append(image_ref)
                self.parts.append(IMAGE_OBJECT)

    def handle_endtag(self, tag):
        if tag in ("head", "style", "script", "noscript") and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")
        if self._heading == tag:
            heading = "".join(self._heading_parts).strip()
            if heading and not self.title:
                self.title = heading
            self._heading = None

    def handle_data(self, data):
        if self._skip_depth:
            return
        self.parts.append(data)
        if self._heading:
            self._heading_parts.append(data)


def html_to_text(source):
    parser = _TextExtractor()
    parser.feed(source)
    text = html.unescape("".join(parser.parts))
    return text, parser.title, parser.images


def clean_text(text, trim=True, repair=True):
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    if trim:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
        compact = []
        blank = False
        for line in lines:
            if line:
                compact.append(line)
                blank = False
            elif not blank:
                compact.append("")
                blank = True
        text = "\n".join(compact).strip()
    if repair:
        # 记事本硬换行：正文句子自动接回，但章节标题与自然段边界必须保留。
        lines = text.splitlines()
        repaired = []
        heading = re.compile(r"^(第.{1,24}[章节回卷篇部][^\n]{0,40}|序章|楔子|前言|后记|尾声)$")
        for index, line in enumerate(lines):
            repaired.append(line)
            if index + 1 >= len(lines):
                continue
            next_line = lines[index + 1]
            keep_break = (
                not line or not next_line or heading.match(line.strip())
                or heading.match(next_line.strip())
                or re.search(r"[。！？!?；;：:\.…”」』]$", line))
            if keep_break:
                repaired.append("\n")
        text = "".join(repaired)
    return text


def split_chapters(text, fallback_title="正文"):
    pattern = re.compile(r"(?m)^(第.{1,24}[章节回卷篇部][^\n]{0,40}|序章|楔子|前言|后记|尾声)\s*$")
    matches = list(pattern.finditer(text))
    if not matches:
        return [{"title": fallback_title, "text": text, "images": []}]
    chapters = []
    if matches[0].start() > 0 and text[:matches[0].start()].strip():
        chapters.append({"title": "前言", "text": text[:matches[0].start()].strip(), "images": []})
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        chapters.append({"title": match.group(1).strip(), "text": body, "images": []})
    return chapters


def _safe_extract(zf, member, target_dir):
    normalized = member.replace("\\", "/").lstrip("/")
    if ".." in Path(normalized).parts:
        return ""
    target = Path(target_dir, normalized).resolve()
    root = Path(target_dir).resolve()
    if root not in target.parents and target != root:
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member) as src, open(target, "wb") as dst:
        dst.write(src.read())
    return str(target)


def _parse_epub(path, asset_dir):
    chapters = []
    title = Path(path).stem
    with zipfile.ZipFile(path) as zf:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = next(
            elem.attrib["full-path"] for elem in container.iter()
            if elem.tag.endswith("rootfile"))
        opf = ET.fromstring(zf.read(rootfile))
        base = str(Path(rootfile).parent).replace("\\", "/")
        manifest = {}
        media = {}
        for elem in opf.iter():
            if elem.tag.endswith("title") and elem.text and title == Path(path).stem:
                title = elem.text.strip()
            if elem.tag.endswith("item"):
                manifest[elem.attrib.get("id")] = elem.attrib.get("href", "")
                media[elem.attrib.get("id")] = elem.attrib.get("media-type", "")
        spine = [
            elem.attrib.get("idref") for elem in opf.iter()
            if elem.tag.endswith("itemref")]
        for index, item_id in enumerate(spine):
            href = manifest.get(item_id, "")
            member = f"{base}/{href}".lstrip("/") if base != "." else href
            try:
                raw = zf.read(member)
            except KeyError:
                continue
            source, _ = decode_bytes(raw)
            text, heading, image_refs = html_to_text(source)
            images = []
            chapter_dir = str(Path(member).parent).replace("\\", "/")
            for ref in image_refs:
                clean_ref = unquote(ref).split("#", 1)[0].split("?", 1)[0]
                image_member = posixpath.normpath(
                    posixpath.join(chapter_dir, clean_ref))
                try:
                    extracted = _safe_extract(zf, image_member, asset_dir)
                    if extracted:
                        images.append(extracted)
                    else:
                        images.append("")
                except KeyError:
                    images.append("")
            text = clean_text(text)
            if text or images:
                chapters.append({
                    "title": heading or f"第 {index + 1} 节",
                    "text": text,
                    "images": images,
                })
    return title, chapters, "EPUB"


def _parse_pdf(path, asset_dir):
    chapters = []
    # 尝试用 PyMuPDF（fitz）解析，任意异常都 fallback 到 pypdf
    doc = None
    try:
        import fitz
        doc = fitz.open(path)
    except Exception:
        pass
    if doc is not None:
        try:
            meta = doc.metadata
            title = (meta or {}).get("title") or Path(path).stem
            for index in range(len(doc)):
                page = doc.load_page(index)
                images = []
                for image_index, item in enumerate(page.get_images(full=True)[:12]):
                    try:
                        data = doc.extract_image(item[0])
                        out = Path(asset_dir, f"page_{index + 1}_img_{image_index + 1}.{data['ext']}")
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(data["image"])
                        images.append(str(out))
                    except Exception:
                        pass
                chapters.append({
                    "title": f"第 {index + 1} 页",
                    "text": clean_text(page.get_text("text")),
                    "images": images,
                })
            return title, chapters, "PDF/PyMuPDF"
        finally:
            doc.close()
    # fallback：用 pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        title = getattr(reader.metadata, "title", "") or Path(path).stem
        for index, page in enumerate(reader.pages):
            chapters.append({
                "title": f"第 {index + 1} 页",
                "text": clean_text(page.extract_text() or ""),
                "images": [],
            })
        return title, chapters, "PDF/pypdf"
    except Exception as exc:
        raise ValueError(f"无法解析 PDF（已尝试 PyMuPDF 和 pypdf）：{exc}") from exc


def parse_ebook(path, asset_dir, trim=True, repair=True):
    path = os.path.abspath(path)
    ext = Path(path).suffix.lower()
    if ext not in SUPPORTED_EBOOKS:
        raise ValueError(f"暂不支持 {ext or '无扩展名'} 格式")
    os.makedirs(asset_dir, exist_ok=True)
    if ext == ".epub":
        title, chapters, encoding = _parse_epub(path, asset_dir)
    elif ext == ".pdf":
        title, chapters, encoding = _parse_pdf(path, asset_dir)
    else:
        raw = Path(path).read_bytes()
        source, encoding = decode_bytes(raw)
        if ext in (".html", ".htm"):
            text, html_title, image_refs = html_to_text(source)
            title = html_title or Path(path).stem
            images = []
            for ref in image_refs:
                candidate = Path(path).parent / ref
                if candidate.is_file():
                    images.append(str(candidate.resolve()))
            chapters = split_chapters(clean_text(text, trim, repair), title)
            if chapters:
                chapters[0]["images"] = images
        else:
            title = Path(path).stem
            chapters = split_chapters(clean_text(source, trim, repair), title)
    if trim or repair:
        for chapter in chapters:
            chapter["text"] = clean_text(chapter.get("text", ""), trim, repair)
    total_chars = sum(len(c.get("text", "")) for c in chapters)
    return {
        "parser_version": PARSER_VERSION,
        "title": title,
        "path": path,
        "extension": ext,
        "encoding": encoding,
        "size": os.path.getsize(path),
        "total_chars": total_chars,
        "chapters": chapters or [{"title": "正文", "text": "", "images": []}],
    }


def cache_path(asset_dir):
    return os.path.join(asset_dir, "content.json")


def save_cache(parsed, asset_dir):
    os.makedirs(asset_dir, exist_ok=True)
    with open(cache_path(asset_dir), "w", encoding="utf-8") as file:
        json.dump(parsed, file, ensure_ascii=False)


def load_cache(asset_dir, source_path):
    path = cache_path(asset_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        if (data.get("parser_version") == PARSER_VERSION
                and data.get("source_mtime") == os.path.getmtime(source_path)):
            return data
    except Exception:
        pass
    return None
