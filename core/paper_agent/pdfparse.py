"""pdfparse.py — 论文精读：零第三方依赖的 PDF 文本提取 + 结构化解析（PRD F-2.1）。

设计目标
--------
在**不引入任何第三方库**（红线：仅标准库）的前提下，尽最大努力把一篇论文
PDF 变成**带位置依据的结构化笔记**：

1. **文本提取**：暴力扫描 PDF 中的 ``stream ... endstream``，用标准库 ``zlib``
   解 FlateDecode，再按 PDF 内容流的文本算子（``Tj`` / ``TJ`` / ``'`` / ``"``）
   抽取可读文本；按内容流顺序编号 **近似页码**。
2. **结构提取**：识别常见章节标题（Abstract/Introduction/Method/…，摘要/引言/方法/…），
   切成 ``sections`` 字典。
3. **关键信息抽取**：方法 / 数据 / 结论 / 局限 —— 依据关键词句窗口抽取，
   每条都带 ``locator``（章节名 + 字符偏移）以便溯源。
4. **可复现性检查**：正则识别代码仓库链接（github/gitlab/zenodo…）与数据集链接。
5. **语言识别**：按 CJK 字符占比判定中/英，**输出笔记跟随原文语言**。
6. **扫描件降级**：无文本层（或文本量过低）→ 标 ``status="scanned"``、
   ``confidence="low"``，并尝试 **OCR 路径**（若系统存在 ``tesseract`` 则调用，
   否则显式标注 ``ocr_unavailable``），符合 PRD「扫描版 PDF → 标注低质量解析」。

边界（必须诚实声明）
--------------------
- 纯标准库无法覆盖 CID/自定义编码字体与复杂版式；此类文件会给出
  ``confidence="low"`` 与 ``warnings``，绝不假装解析成功。
- 页码为「内容流序号」近似值，用于给结论提供可核查的定位入口，不是出版页码。
- 扫描件 OCR 依赖外部可执行文件 ``tesseract``（可选）；缺失时降级而非编造内容。

用法::

    from paper_agent import pdfparse
    note = pdfparse.parse_paper("data/sample.pdf")           # 本地 PDF
    note = pdfparse.parse_paper("2301.12345", allow_network=True)  # arXiv ID
    md = pdfparse.render_note(note, "zh")
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
import zlib

_MIN_TEXT_CHARS = 200          # 文本量"充足"的参考阈值（用于告警，不用于 has_text_layer）
_LOW_CONF_CHARS = 800          # 低于此字符数 → 置信度 low
_ARXIV_PDF = "https://arxiv.org/pdf/{id}"
_UA = "paper-agent/1.1 (research hackathon demo)"

# ---- 章节标题词表（英文 + 中文），顺序即优先级 ----
_SECTION_PATTERNS: list[tuple[str, str]] = [
    ("Abstract", r"^(?:\d+\.?\s*)?abstract\b"),
    ("摘要", r"^摘\s*要"),
    ("Introduction", r"^(?:\d+\.?\s*)?introduction\b"),
    ("引言", r"^引\s*言"),
    ("Related Work", r"^(?:\d+\.?\s*)?(related work|background|literature review)\b"),
    ("相关工作", r"^相关工作"),
    ("Method", r"^(?:\d+\.?\s*)?(method(?:s|ology)?|approach|proposed (?:method|model|framework))\b"),
    ("方法", r"^(?:方法|模型|算法)"),
    ("Experiment", r"^(?:\d+\.?\s*)?(experiment(?:s|al)?|evaluation|results and discussion)\b"),
    ("实验", r"^(?:实验|评估)"),
    ("Results", r"^(?:\d+\.?\s*)?results?\b"),
    ("Discussion", r"^(?:\d+\.?\s*)?discussion\b"),
    ("Conclusion", r"^(?:\d+\.?\s*)?conclusions?\b"),
    ("结论", r"^结\s*论"),
    ("Limitations", r"^(?:\d+\.?\s*)?limitations?\b"),
    ("局限", r"^(?:局限|不足)"),
    ("Future Work", r"^(?:\d+\.?\s*)?future work\b"),
    ("References", r"^(?:\d+\.?\s*)?references\b"),
    ("参考文献", r"^参考文献"),
    ("Acknowledg", r"^(?:\d+\.?\s*)?acknowledg"),
]
_HEADING_MAX_LEN = 60          # 章节标题行长度上限（避免把正文句子当标题）

_CODE_HOSTS = re.compile(
    r"(?:https?://)?(?:www\.)?(github\.com|gitlab\.com|bitbucket\.org|"
    r"huggingface\.co|zenodo\.org|osf\.io|sourceforge\.net)/[\w\-./#?=&%]+", re.I)
_DATA_HOSTS = re.compile(
    r"(?:https?://)?(?:www\.)?(?:kaggle\.com|zenodo\.org|figshare\.com|"
    r"data\.mendeley\.com|openml\.org|paperswithcode\.com|dataverse\.[\w.]+)/[\w\-./#?=&%]+", re.I)
_URL_ANY = re.compile(r"https?://[\w\-./#?=&%~+]+", re.I)


# =====================================================================
# 1) PDF 文本提取（纯标准库）
# =====================================================================

def _inflate(raw: bytes) -> bytes:
    """尝试 zlib 解压（FlateDecode）；失败则原样返回（可能是未压缩流）。"""
    try:
        return zlib.decompress(raw)
    except Exception:
        try:
            return zlib.decompressobj().decompress(raw)
        except Exception:
            return raw


def _iter_streams(pdf: bytes):
    """暴力扫描 ``stream ... endstream``，逐个解压后 yield。"""
    for m in re.finditer(rb"stream\r?\n", pdf):
        start = m.end()
        end = pdf.find(b"endstream", start)
        if end == -1:
            continue
        raw = pdf[start:end].rstrip(b"\r\n")
        yield _inflate(raw)


_ESCAPE = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
_NUM_RE = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)$")   # 裸数字 token（操作数，非算子）


def _content_text(data: bytes) -> str:
    """从一段内容流中按文本算子抽取文本（含页内换行）。"""
    out: list[str] = []
    operands: list[str] = []
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        # --- 字面字符串 ( ... ) ---
        if c == 0x28:
            j = i + 1
            buf = bytearray()
            depth = 1
            while j < n:
                ch = data[j]
                if ch == 0x5C:                      # 反斜杠转义
                    if j + 1 < n:
                        nxt = data[j + 1]
                        if nxt in _ESCAPE:
                            buf.append(_ESCAPE[nxt]); j += 2; continue
                        if 0x30 <= nxt <= 0x37:     # 八进制 \ddd
                            k, val, cnt = j + 1, 0, 0
                            while k < n and cnt < 3 and 0x30 <= data[k] <= 0x37:
                                val = val * 8 + (data[k] - 0x30); k += 1; cnt += 1
                            buf.append(val & 0xFF); j = k; continue
                        buf.append(nxt); j += 2; continue
                    j += 1; continue
                if ch == 0x28:
                    depth += 1
                elif ch == 0x29:
                    depth -= 1
                    if depth == 0:
                        j += 1; break
                buf.append(ch); j += 1
            operands.append(bytes(buf).decode("latin-1"))
            i = j
            continue
        # --- 十六进制字符串 < ... > ---
        if c == 0x3C and i + 1 < n and data[i + 1] != 0x3C:
            j = data.find(b">", i + 1)
            if j == -1:
                break
            hx = re.sub(rb"[^0-9A-Fa-f]", b"", data[i + 1:j])
            if len(hx) % 2:
                hx += b"0"
            try:
                raw = bytes.fromhex(hx.decode("ascii"))
                if raw[:2] == b"\xfe\xff":
                    operands.append(raw[2:].decode("utf-16-be", "ignore"))
                else:
                    operands.append(raw.decode("latin-1"))
            except Exception:
                pass
            i = j + 1
            continue
        # --- 操作符 / 数字（空白分隔的裸 token）---
        if c in (0x20, 0x0A, 0x0D, 0x09, 0x5B, 0x5D):
            i += 1
            continue
        if c == 0x2F:                                # /Name
            j = i + 1
            while j < n and data[j] not in b" \t\r\n/[]<>()":
                j += 1
            i = j
            continue
        # 读取一个 token
        j = i
        while j < n and data[j] not in b" \t\r\n/[]<>()":
            j += 1
        token = data[i:j].decode("latin-1")
        i = j
        if token in ("Tj", "TJ", "'", '"'):
            if operands:
                out.append("".join(operands))
            if token in ("'", '"'):
                out.append("\n")
            operands = []
        elif token in ("Td", "TD", "T*"):
            out.append("\n")
            operands = []
        elif _NUM_RE.match(token):
            # 数字是**操作数**（如 TJ 数组中的字距微调 -250），
            # 不代表文本算子结束，必须保留已收集的字符串操作数。
            pass
        else:
            operands = []          # 非文本算子：丢弃暂存操作数
    return "".join(out)


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    # 去掉连续空行；保留段落感
    out: list[str] = []
    blank = 0
    for ln in lines:
        if ln:
            out.append(ln); blank = 0
        else:
            blank += 1
            if blank <= 1:
                out.append("")
    return "\n".join(out).strip()


def extract_pdf_text(pdf_bytes: bytes) -> dict:
    """从 PDF 字节流提取文本。返回 ``{text, n_pages, n_chars, has_text_layer, pages}``。

    ``pages`` 为**近似**分页文本列表（按内容流顺序），用于给结论提供定位入口。
    """
    pages: list[str] = []
    for stream in _iter_streams(pdf_bytes):
        if b"Tj" not in stream and b"TJ" not in stream and b"BT" not in stream:
            continue
        txt = _content_text(stream)
        txt = _normalize_text(txt)
        if txt:
            pages.append(txt)
    text = "\n\n".join(pages)
    n_chars = len(text)
    return {
        "text": text,
        "pages": pages,
        "n_pages": len(pages),
        "n_chars": n_chars,
        # 「存在文本层」= 抽取到任意可读文本；文本量是否充足由 confidence 判定。
        # 扫描件无任何文本算子 → n_chars==0 → False，正确降级。
        "has_text_layer": n_chars > 0,
    }


# =====================================================================
# 2) OCR 降级路径（可选外部依赖 tesseract）
# =====================================================================

def ocr_available() -> bool:
    return shutil.which("tesseract") is not None and shutil.which("pdftoppm") is not None


def try_ocr(pdf_path: str, out_dir: str | None = None) -> str | None:
    """尝试 OCR：``pdftoppm`` 转图 + ``tesseract`` 识别。不可用/失败返回 None。"""
    if not ocr_available():
        return None
    out_dir = out_dir or os.path.dirname(os.path.abspath(pdf_path))
    try:
        os.makedirs(out_dir, exist_ok=True)
        prefix = os.path.join(out_dir, "_ocr_page")
        subprocess.run(["pdftoppm", "-png", "-r", "200", pdf_path, prefix],
                       capture_output=True, timeout=180, check=True)
        chunks: list[str] = []
        for fn in sorted(os.listdir(out_dir)):
            if fn.startswith("_ocr_page") and fn.endswith(".png"):
                img = os.path.join(out_dir, fn)
                r = subprocess.run(["tesseract", img, "stdout"],
                                   capture_output=True, text=True, timeout=120)
                if r.returncode == 0 and r.stdout.strip():
                    chunks.append(r.stdout.strip())
        return "\n\n".join(chunks) if chunks else None
    except Exception:
        return None


# =====================================================================
# 3) 结构与关键信息
# =====================================================================

def detect_language(text: str) -> str:
    """按 CJK 字符占比判定语言：中/英。"""
    if not text:
        return "en"
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return "zh" if cjk / max(1, len(text)) > 0.05 else "zh" if cjk > 40 else "en"


def _match_heading(line: str) -> str | None:
    if not line or len(line) > _HEADING_MAX_LEN:
        return None
    for name, pat in _SECTION_PATTERNS:
        if re.match(pat, line, re.I):
            return name
    return None


def split_sections(text: str) -> dict:
    """按章节标题切分；未识别到标题时整体归入 ``Body``。"""
    sections: dict[str, list[str]] = {}
    cur = "Body"
    sections[cur] = []
    for line in text.split("\n"):
        head = _match_heading(line)
        if head:
            cur = head
            sections.setdefault(cur, [])
            continue
        sections[cur].append(line)
    return {k: _normalize_text("\n".join(v)) for k, v in sections.items() if _normalize_text("\n".join(v))}


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 20]


_KEYWORD_MAP = {
    "method": ("we propose", "we present", "we introduce", "our method", "our approach",
               "we develop", "we design", "本文提出", "我们提出", "本文设计"),
    "data": ("dataset", "datasets", "corpus", "we evaluate on", "trained on",
             "benchmark", "数据集", "语料", "在…上评测"),
    "conclusion": ("we conclude", "in conclusion", "results show", "we find",
                   "our results", "experiments show", "表明", "结论", "结果显示"),
    "limitations": ("limitation", "limited", "however", "future work", "drawback",
                    "caveat", "局限", "不足", "未来工作"),
}


def extract_key_info(sections: dict, text: str) -> dict:
    """抽取方法/数据/结论/局限四类关键信息，每条带 locator（章节+字符偏移）。"""
    result: dict[str, list[dict]] = {k: [] for k in _KEYWORD_MAP}
    for sec_name, sec_text in sections.items():
        for sent in _sentences(sec_text):
            low = sent.lower()
            for kind, kws in _KEYWORD_MAP.items():
                if any(kw in low for kw in kws):
                    if len(result[kind]) >= 5:
                        continue
                    result[kind].append({
                        "text": sent,
                        "locator": {"section": sec_name,
                                    "offset": text.find(sent[:40]) if sent[:40] else -1},
                    })
    return result


def extract_figures_tables(text: str) -> list[dict]:
    """识别 Figure/Table/图/表 的**标题**（caption: 后接标题文本）。

    采用「编号 + 冒号/句点 + 标题」的 caption 样式，规避 "as shown in Figure 1"
    这类正文引用；最多返回 30 条。
    """
    out: list[dict] = []
    pat = re.compile(
        r"(?:^|[\s(])(figure|fig\.?|table|图|表)\s*(\d+)\s*[:：.]\s*"
        r"([A-Za-z\u4e00-\u9fff][^\n]{4,300})", re.I)
    seen: set[tuple] = set()
    for m in pat.finditer(text):
        kind = "table" if m.group(1).lower().startswith(("table", "表")) else "figure"
        idx = int(m.group(2))
        key = (kind, idx)
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": kind, "index": idx, "caption": m.group(3).strip()[:300]})
        if len(out) >= 30:
            break
    return out


def check_reproducibility(text: str) -> dict:
    """检查可复现性：代码链接 / 数据集链接 / 是否声明开源。"""
    code = sorted({m.group(0) for m in _CODE_HOSTS.finditer(text)})
    data = sorted({m.group(0) for m in _DATA_HOSTS.finditer(text)})
    code = [c if c.startswith("http") else "https://" + c for c in code]
    data = [d if d.startswith("http") else "https://" + d for d in data]
    return {
        "code_links": code,
        "dataset_links": data,
        "has_code": bool(code),
        "has_data": bool(data),
    }


# =====================================================================
# 4) 顶层入口：parse_paper
# =====================================================================

def _read_pdf_bytes(source: str, allow_network: bool) -> tuple[bytes | None, str, str]:
    """返回 ``(pdf_bytes|None, 规范化来源标识, 说明)``。"""
    if os.path.exists(source):
        with open(source, "rb") as f:
            return f.read(), os.path.basename(source), "local_file"
    if not allow_network:
        return None, source, "not_found_offline"
    arxiv_id = re.sub(r"^arxiv:", "", source.strip(), flags=re.I)
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", arxiv_id):
        try:
            req = urllib.request.Request(_ARXIV_PDF.format(id=arxiv_id),
                                         headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=40) as resp:
                return resp.read(), f"arXiv:{arxiv_id}", "arxiv_pdf"
        except Exception as e:
            return None, f"arXiv:{arxiv_id}", f"arxiv_fetch_failed:{type(e).__name__}"
    return None, source, "unsupported_source"


def parse_pdf_bytes(pdf_bytes: bytes, doc_id: str = "<memory>",
                    ocr_source_path: str | None = None,
                    out_dir: str | None = None) -> dict:
    """核心解析：从 PDF 字节流构建结构化笔记（不涉及网络）。

    ``ocr_source_path`` 供扫描件场景定位磁盘文件做 OCR（可选）。
    """
    note: dict = {
        "source": doc_id, "doc_id": doc_id, "title": "", "language": "en",
        "status": "failed", "confidence": "low", "extractor": "",
        "n_pages": 0, "n_chars": 0, "sections": {}, "key_info": {},
        "figures_tables": [], "reproducibility": {},
        "warnings": [], "text": "",
    }
    ext = extract_pdf_text(pdf_bytes)
    note["n_pages"] = ext["n_pages"]
    note["n_chars"] = ext["n_chars"]
    note["extractor"] = "stdlib-zlib+content-ops"
    text = ext["text"]
    ocr_used = False

    if not ext["has_text_layer"]:
        ocr_text = try_ocr(ocr_source_path, out_dir) if ocr_source_path else None
        if ocr_text:
            text = ocr_text
            note["extractor"] = "ocr:tesseract"
            ocr_used = True
            note["warnings"].append("原文无文本层，已走 OCR 路径，识别置信度偏低")
        else:
            note["status"] = "scanned"
            note["confidence"] = "low"
            note["warnings"].append(
                "该 PDF 为扫描件（无可提取文本层），OCR 路径不可用（未检测到 tesseract）；"
                "未提取到正文文本，解析置信度低")
            note["language"] = detect_language(text)
            note["text"] = text
            note["sections"] = split_sections(text)
            note["key_info"] = extract_key_info(note["sections"], text)
            note["figures_tables"] = extract_figures_tables(text)
            note["reproducibility"] = check_reproducibility(text)
            return note

    note["language"] = detect_language(text)
    note["sections"] = split_sections(text)
    note["key_info"] = extract_key_info(note["sections"], text)
    note["figures_tables"] = extract_figures_tables(text)
    note["reproducibility"] = check_reproducibility(text)
    note["text"] = text

    for line in text.split("\n"):
        if 5 <= len(line) <= 300:
            note["title"] = line
            break

    printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\t")
    ratio = printable / max(1, len(text))
    # 三档置信度：长文本+高可打印率=high；有真实文本但偏短=medium；近乎无文本/编码异常=low
    if note["n_chars"] >= _LOW_CONF_CHARS and ratio >= 0.9:
        note["confidence"] = "high" if not ocr_used else "medium"
    elif note["n_chars"] >= _MIN_TEXT_CHARS and ratio >= 0.9:
        note["confidence"] = "medium"
        note["warnings"].append(
            f"提取文本量偏少（chars={note['n_chars']} < {_LOW_CONF_CHARS}），"
            "可能是摘要/元数据版式而非论文全文，解析置信度中等")
    else:
        note["confidence"] = "low"
        if note["n_chars"] < _MIN_TEXT_CHARS:
            note["warnings"].append(
                f"提取文本量过少（chars={note['n_chars']} < {_MIN_TEXT_CHARS}），"
                "可能是扫描件或极简版式，解析置信度低")
        if ratio < 0.9:
            note["warnings"].append(
                f"可打印字符比例偏低（ratio={ratio:.2f}），"
                "可能为 CID/自定义编码字体，解析置信度低")
    note["status"] = "ok"
    return note


def parse_paper(source: str, allow_network: bool = False,
                out_dir: str | None = None) -> dict:
    """论文精读主入口。

    ``source`` 可为：本地 PDF 路径 / arXiv ID（如 ``2301.12345``）/ DOI。
    返回结构化笔记 dict（见模块 docstring）。**绝不编造内容**：
    解析失败即如实标注 ``status`` 与 ``warnings``。
    """
    pdf_bytes, doc_id, why = _read_pdf_bytes(source, allow_network)
    if pdf_bytes is None:
        note = parse_pdf_bytes(b"", doc_id)
        note["source"] = source
        note["status"] = "unavailable"
        note["warnings"].append(f"无法获取 PDF（{why}）")
        return note
    note = parse_pdf_bytes(pdf_bytes, doc_id,
                           ocr_source_path=(source if os.path.exists(source) else None),
                           out_dir=out_dir)
    note["source"] = source
    return note


# =====================================================================
# 5) 结构化笔记渲染（语言跟随原文）
# =====================================================================

_LABELS = {
    "zh": {"title": "标题", "source": "来源", "status": "解析状态", "conf": "置信度",
           "pages": "近似页数", "lang": "语言", "method": "方法", "data": "数据",
           "conclusion": "结论", "limitations": "局限", "figs": "图表",
           "repro": "可复现性", "sections": "章节结构", "warn": "警告"},
    "en": {"title": "Title", "source": "Source", "status": "Status", "conf": "Confidence",
           "pages": "Approx. pages", "lang": "Language", "method": "Method", "data": "Data",
           "conclusion": "Conclusion", "limitations": "Limitations", "figs": "Figures/Tables",
           "repro": "Reproducibility", "sections": "Sections", "warn": "Warnings"},
}


def render_note(note: dict, lang: str | None = None) -> str:
    """把结构化笔记渲染为 Markdown；``lang`` 缺省跟随原文语言。"""
    lang = (lang or note.get("language") or "en")
    lang = "zh" if lang == "zh" else "en"
    L = _LABELS[lang]
    lines = [f"# {note.get('title') or note.get('doc_id') or '(untitled)'}", ""]
    lines.append(f"- {L['source']}: `{note.get('doc_id')}`")
    lines.append(f"- {L['status']}: {note.get('status')} / {L['conf']}: {note.get('confidence')}")
    lines.append(f"- {L['pages']}: {note.get('n_pages')} | {L['lang']}: {note.get('language')}")
    if note.get("warnings"):
        lines.append(f"- ⚠️ {L['warn']}: " + "; ".join(note["warnings"]))
    lines.append("")

    ki = note.get("key_info") or {}
    for kind in ("method", "data", "conclusion", "limitations"):
        items = ki.get(kind) or []
        if not items:
            continue
        lines.append(f"## {L[kind]}")
        for it in items:
            loc = it.get("locator") or {}
            tag = f"[{loc.get('section', '?')}@off={loc.get('offset', -1)}]"
            lines.append(f"- {it['text']} `{tag}`")
        lines.append("")

    figs = note.get("figures_tables") or []
    if figs:
        lines.append(f"## {L['figs']}")
        for f in figs:
            lines.append(f"- ({f['kind']} {f['index']}) {f['caption']}")
        lines.append("")

    rep = note.get("reproducibility") or {}
    lines.append(f"## {L['repro']}")
    lines.append(f"- code: {rep.get('has_code')} {rep.get('code_links') or ''}")
    lines.append(f"- data: {rep.get('has_data')} {rep.get('dataset_links') or ''}")
    lines.append("")

    secs = note.get("sections") or {}
    if secs:
        lines.append(f"## {L['sections']}")
        for name, body in secs.items():
            lines.append(f"### {name} ({len(body)} chars)")
            lines.append(body[:1500] + ("…" if len(body) > 1500 else ""))
            lines.append("")
    return "\n".join(lines)


__all__ = [
    "extract_pdf_text", "split_sections", "extract_key_info",
    "extract_figures_tables", "check_reproducibility", "detect_language",
    "parse_paper", "parse_pdf_bytes", "render_note", "ocr_available", "try_ocr",
]
