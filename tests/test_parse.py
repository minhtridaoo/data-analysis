"""Test parser bằng HTML TỰ DỰNG mô phỏng cấu trúc TechPowerUp (không phải trang thật).
Trang thật được kiểm bằng `python scraper/tpu_scraper.py probe`.
Chạy: python -m pytest tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
from tpu_parse import (extract_links, gpu_id_from_href, is_blocked_page,  # noqa: E402
                       parse_detail, parse_list, release_year)

ROOT = Path(__file__).resolve().parent.parent

PAD = "<!-- " + "x" * 2500 + " -->"

DETAIL = f"""<html><head><title>NVIDIA GeForce RTX 4090 Specs | TechPowerUp GPU Database</title></head><body>
<h1 class="gpudb-name">NVIDIA GeForce RTX 4090</h1>
<section class="details"><h2>Graphics Processor</h2><div class="sectioncontainer">
 <dl class="clearfix"><dt>GPU Name</dt><dd>AD102</dd></dl>
 <dl class="clearfix"><dt>Architecture</dt><dd>Ada Lovelace</dd></dl>
 <dl class="clearfix"><dt>Process Size</dt><dd>5 nm</dd></dl>
 <dl class="clearfix"><dt>Transistors</dt><dd>76,300 million</dd></dl>
</div></section>
<section class="details"><h2>Graphics Card</h2>
 <dl><dt>Release Date</dt><dd>Sep 20th, 2022</dd></dl>
 <dl><dt>Launch Price</dt><dd>1,599 USD</dd></dl>
</section>
<section class="details"><h2>Clock Speeds</h2>
 <dl><dt>Base Clock</dt><dd>2235 MHz</dd></dl>
 <dl><dt>Memory Clock</dt><dd>1313 MHz<br>21 Gbps effective</dd></dl>
</section>
<section class="details"><h2>Render Config (per GPU)</h2>
 <dl><dt>Shading Units</dt><dd>16384</dd></dl>
</section>
<section class="details"><h2>Theoretical Performance</h2>
 <dl><dt>FP32 (float)</dt><dd>82.58 TFLOPS</dd></dl>
</section>
<section class="details"><h2>Power</h2><dl><dt>TDP:</dt><dd>450 W</dd></dl></section>
{PAD}</body></html>"""

LIST = f"""<html><body>
<form><select name="mfgr"><option value="">All</option><option value="NVIDIA">NVIDIA</option>
<option value="AMD">AMD</option></select>
<select name="released"><option value="">All</option><option value="2022">2022</option></select></form>
<table class="processors"><thead><tr><th>Product Name</th><th>GPU Chip</th><th>Released</th></tr></thead>
<tr><td><a href="/gpu-specs/geforce-rtx-4090.c3889">GeForce RTX 4090</a></td><td>AD102</td><td>Sep 20th, 2022</td></tr>
<tr><td><a href="/gpu-specs/geforce-rtx-4080.c3888">GeForce RTX 4080</a></td><td>AD103</td><td>Sep 20th, 2022</td></tr>
<tr><td><a href="/gpu-specs/geforce-rtx-4090.c3889">dup</a></td><td></td><td></td></tr>
</table>{PAD}</body></html>"""


def test_detail_fields_and_fallbacks():
    rec, all_fields = parse_detail(DETAIL)
    assert rec["product_name"] == "NVIDIA GeForce RTX 4090"
    assert rec["gpu_chip"] == "AD102"
    assert rec["transistors"] == "76,300 million"
    assert rec["launch_price"] == "1,599 USD"
    assert rec["memory_clock"] == "1313 MHz 21 Gbps effective"  # <br> được nối bằng dấu cách
    assert rec["shading_units"] == "16384"                       # section có hậu tố "(per GPU)"
    assert rec["tdp"] == "450 W"                                 # nhãn có ':' + section lạ -> fallback
    assert rec["boost_clock"] == ""                              # trường khuyết -> chuỗi rỗng, không lỗi
    assert all_fields["Graphics Processor::Architecture"] == "Ada Lovelace"


def test_list_dedupe_and_columns():
    rows = parse_list(LIST)
    assert [r["gpu_id"] for r in rows] == ["c3889", "c3888"]
    assert rows[0]["url"] == "https://www.techpowerup.com/gpu-specs/geforce-rtx-4090.c3889"
    assert rows[1]["list_gpu_chip"] == "AD103"


def test_links_skip_query_urls():
    html = ('<a href="/gpu-specs/radeon-rx-9070-xt.c4229">x</a><a href="/gpu-specs/amd-navi-48.g1071">y</a>'
            '<a href="/gpu-specs/radeon-rx-9070-xt.c4229">dup</a><a href="/gpu-specs/?mfgr=AMD">trap</a>'
            '<a href="https://www.techpowerup.com/gpu-specs/geforce-rtx-5090.c4216">abs</a>')
    assert extract_links(html) == [
        ("c4229", "https://www.techpowerup.com/gpu-specs/radeon-rx-9070-xt.c4229"),
        ("g1071", "https://www.techpowerup.com/gpu-specs/amd-navi-48.g1071"),
        ("c4216", "https://www.techpowerup.com/gpu-specs/geforce-rtx-5090.c4216")]


def test_generic_layout_without_section_tags():
    html = ("<h1>AMD Radeon RX 9070 XT</h1><div><h2>Memory</h2><dl><dt>Memory Size</dt><dd>16 GB</dd></dl>"
            "<h2>Graphics Card</h2><dl><dt>Release Date</dt><dd>Mar 6th, 2025</dd></dl></div>")
    rec, _ = parse_detail(html)
    assert rec["memory_size"] == "16 GB" and rec["release_date"] == "Mar 6th, 2025"
    assert release_year(rec["release_date"]) == 2025 and release_year("Never Released") is None


def test_real_base_page_if_cached():
    p = ROOT / "data" / "cache" / "lists" / "_base.html"
    if not p.exists():
        return
    links = extract_links(p.read_text(encoding="utf-8"))
    assert sum(k.startswith("c") for k, _ in links) >= 50
    assert sum(k.startswith("g") for k, _ in links) >= 20
    assert not is_blocked_page(p.read_text(encoding="utf-8"))


def test_href_and_block_detection():
    assert gpu_id_from_href("/gpu-specs/radeon-rx-7900-xtx.c3941") == "c3941"
    assert gpu_id_from_href("/gpu-specs/?mfgr=AMD") is None
    assert not is_blocked_page(DETAIL)
    assert is_blocked_page("<html>Please complete the captcha</html>")
    assert is_blocked_page("<html>" + "y" * 5000 + " cf-chl challenge</html>")
