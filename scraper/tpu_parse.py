"""Bóc tách HTML của TechPowerUp GPU Database — KHÔNG truy cập mạng.

Tách riêng khỏi phần tải trang để có thể test offline và parse lại từ cache
bất cứ lúc nào mà không phải crawl lại.

Cấu trúc trang chi tiết (đã biết, cần xác nhận bằng lệnh `probe`):
    <h1 class="gpudb-name">NVIDIA GeForce RTX 4090</h1>
    <section class="details">
        <h2>Graphics Processor</h2>
        <dl><dt>GPU Name</dt><dd>AD102</dd></dl> ...
    </section>
Parser đọc TẤT CẢ cặp dt/dd theo từng section nên không phụ thuộc thứ tự,
và FIELD_MAP chỉ là bước chọn cột (có alias + fallback tìm theo nhãn).
"""
from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup

GPU_HREF_RE = re.compile(r"^(?:https?://www\.techpowerup\.com)?/gpu-specs/[^/?#]+\.c(\d+)/?$")

# cột raw -> danh sách (section, nhãn) theo thứ tự ưu tiên.
# section=None nghĩa là tìm ở mọi section.
FIELD_MAP: dict[str, list[tuple[str | None, str]]] = {
    # Graphics Processor
    "gpu_chip": [("Graphics Processor", "GPU Name")],
    "gpu_variant": [("Graphics Processor", "GPU Variant")],
    "architecture": [("Graphics Processor", "Architecture")],
    "foundry": [("Graphics Processor", "Foundry")],
    "process_size": [("Graphics Processor", "Process Size")],
    "transistors": [("Graphics Processor", "Transistors")],
    "density": [("Graphics Processor", "Density")],
    "die_size": [("Graphics Processor", "Die Size")],
    # Graphics Card
    "release_date": [("Graphics Card", "Release Date")],
    "availability": [("Graphics Card", "Availability")],
    "generation": [("Graphics Card", "Generation")],
    "production": [("Graphics Card", "Production")],
    "launch_price": [("Graphics Card", "Launch Price")],
    "bus_interface": [("Graphics Card", "Bus Interface")],
    # Clock Speeds
    "base_clock": [("Clock Speeds", "Base Clock"), ("Clock Speeds", "GPU Clock")],
    "game_clock": [("Clock Speeds", "Game Clock")],
    "boost_clock": [("Clock Speeds", "Boost Clock")],
    "memory_clock": [("Clock Speeds", "Memory Clock"), (None, "Memory Clock")],
    # Memory
    "memory_size": [("Memory", "Memory Size")],
    "memory_type": [("Memory", "Memory Type")],
    "memory_bus": [("Memory", "Memory Bus")],
    "bandwidth": [("Memory", "Bandwidth")],
    # Render Config
    "shading_units": [("Render Config", "Shading Units")],
    "tmus": [("Render Config", "TMUs")],
    "rops": [("Render Config", "ROPs")],
    "sm_count": [("Render Config", "SM Count")],
    "compute_units": [("Render Config", "Compute Units")],
    "execution_units": [("Render Config", "Execution Units")],
    "tensor_cores": [("Render Config", "Tensor Cores")],
    "rt_cores": [("Render Config", "RT Cores")],
    "l1_cache": [("Render Config", "L1 Cache")],
    "l2_cache": [("Render Config", "L2 Cache")],
    "l3_cache": [("Render Config", "L3 Cache")],
    # Theoretical Performance
    "pixel_rate": [("Theoretical Performance", "Pixel Rate")],
    "texture_rate": [("Theoretical Performance", "Texture Rate")],
    "fp16": [("Theoretical Performance", "FP16"), ("Theoretical Performance", "FP16 (half)")],
    "fp32": [("Theoretical Performance", "FP32"), ("Theoretical Performance", "FP32 (float)")],
    "fp64": [("Theoretical Performance", "FP64"), ("Theoretical Performance", "FP64 (double)")],
    # Board Design
    "slot_width": [("Board Design", "Slot Width")],
    "length": [("Board Design", "Length")],
    "tdp": [("Board Design", "TDP"), (None, "TDP"), (None, "TBP")],
    "suggested_psu": [("Board Design", "Suggested PSU")],
    "outputs": [("Board Design", "Outputs")],
    "power_connectors": [("Board Design", "Power Connectors")],
    # Graphics Features
    "directx": [("Graphics Features", "DirectX")],
    "opengl": [("Graphics Features", "OpenGL")],
    "opencl": [("Graphics Features", "OpenCL")],
    "vulkan": [("Graphics Features", "Vulkan")],
    "cuda": [("Graphics Features", "CUDA")],
    "shader_model": [("Graphics Features", "Shader Model")],
}

# Cột lõi: nếu tỉ lệ điền < ngưỡng thì gần như chắc chắn nhãn trên trang đã đổi.
CORE_FIELDS = ["gpu_chip", "architecture", "release_date", "memory_type", "shading_units", "fp32"]

BLOCK_MARKERS = (
    "captcha", "cf-chl", "challenge-platform", "access denied",
    "too many requests", "rate limit", "are you a human", "unusual traffic",
)


def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s.rstrip(":").strip().lower()


def _text(tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip() if tag else ""


def gpu_id_from_href(href: str) -> str | None:
    m = GPU_HREF_RE.match(href or "")
    return f"c{m.group(1)}" if m else None


LINK_RE = re.compile(r'href="(?:https?://www\.techpowerup\.com)?(/gpu-specs/[a-z0-9][a-z0-9-]*\.([cg])(\d+))"', re.I)


def extract_links(html: str) -> list[tuple[str, str]]:
    """Link công khai tới trang card (c) và trang chip (g): [(kind+id, url)].
    Cố ý KHÔNG lấy URL có query string — bộ lọc của site là bẫy bot (spidertrap)."""
    out, seen = [], set()
    for m in LINK_RE.finditer(html or ""):
        key = m.group(2).lower() + m.group(3)
        if key not in seen:
            seen.add(key)
            out.append((key, "https://www.techpowerup.com" + m.group(1).lower()))
    return out


def is_blocked_page(html: str) -> bool:
    """True nếu trang là captcha/chặn chứ không phải nội dung thật."""
    low = (html or "").lower()
    if "/gpu-specs/" in low and ("<dt" in low or "item-name" in low or 'class="details"' in low):
        return False
    return any(m in low for m in BLOCK_MARKERS) or len(low) < 2000


# ---------------------------------------------------------------- trang chi tiết
def extract_sections(html: str) -> tuple[str, dict[str, dict[str, str]]]:
    """Trả về (tên sản phẩm, {section: {nhãn: giá trị}}). Section lặp lại (card 2 GPU) lấy bản đầu.

    Tổng quát để chịu được thay đổi giao diện: duyệt MỌI <dt>, tên section là
    tiêu đề h2/h3 gần nhất phía trước (trong <section> nếu có).
    """
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.select_one("h1.gpudb-name") or soup.find("h1")
    name = _text(h1)
    if not name and soup.title:
        name = _text(soup.title).split(" Specs")[0]

    sections: dict[str, dict[str, str]] = {}
    for dt in soup.find_all("dt"):
        sec = dt.find_parent("section")
        head = sec.find(["h2", "h3"]) if sec else None
        if head is None:
            head = dt.find_previous(["h2", "h3"])
        sname = _text(head) or "Unknown"
        bucket = sections.setdefault(sname, {})
        dd = dt.find_next_sibling("dd")
        label = _text(dt)
        if label and label not in bucket:
            bucket[label] = _text(dd)
    return name, sections


def _lookup(sections: dict[str, dict[str, str]], wanted: Iterable[tuple[str | None, str]], *, allow_fallback: bool = True) -> str:
    wanted = list(wanted)
    norm_secs = {_norm(k): {_norm(l): v for l, v in d.items()} for k, d in sections.items()}
    # 1) đúng section (cho phép tên section có hậu tố, vd "Render Config (per GPU)")
    for sec, label in wanted:
        if sec is None:
            continue
        for sname, fields in norm_secs.items():
            if sname.startswith(_norm(sec)) and _norm(label) in fields:
                return fields[_norm(label)]
    if not allow_fallback:
        return ""
    # 2) fallback: nhãn ở bất kỳ section nào
    for _, label in wanted:
        for fields in norm_secs.values():
            if _norm(label) in fields:
                return fields[_norm(label)]
    return ""


def parse_detail(html: str) -> tuple[dict[str, str], dict[str, str]]:
    """Trả về (bản ghi theo FIELD_MAP, toàn bộ trường dạng 'Section::Label')."""
    name, sections = extract_sections(html)
    rec = {"product_name": name}
    for col, wanted in FIELD_MAP.items():
        # FP labels also occur in Matrix Performance with different meanings.
        rec[col] = _lookup(sections, wanted, allow_fallback=col not in {"fp16", "fp32", "fp64"})
    all_fields = {f"{s}::{l}": v for s, d in sections.items() for l, v in d.items()}
    return rec, all_fields


# ---------------------------------------------------------------- trang danh sách
def parse_list(html: str) -> list[dict[str, str]]:
    """Mỗi dòng của bảng kết quả -> {url, gpu_id, list_<cột>...}."""
    soup = BeautifulSoup(html, "lxml")
    tables = soup.select("table.processors") or soup.find_all("table")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for table in tables:
        headers = [_norm(_text(th)) for th in table.select("thead th")] or \
                  [_norm(_text(th)) for th in table.find_all("th")]
        for tr in table.find_all("tr"):
            a = next((a for a in tr.find_all("a", href=True) if gpu_id_from_href(a["href"])), None)
            if a is None:
                continue
            gid = gpu_id_from_href(a["href"])
            if gid in seen:
                continue
            seen.add(gid)
            href = a["href"]
            url = href if href.startswith("http") else "https://www.techpowerup.com" + href
            row = {"gpu_id": gid, "url": url, "list_name": _text(a)}
            for i, td in enumerate(tr.find_all("td")):
                key = headers[i] if i < len(headers) and headers[i] else f"col{i}"
                key = "list_" + re.sub(r"[^a-z0-9]+", "_", key).strip("_")
                row.setdefault(key, _text(td))
            rows.append(row)
    return rows


def release_year(s: str) -> int | None:
    m = re.search(r"\b(19[89]\d|20\d{2})\b", s or "")
    return int(m.group(1)) if m else None
