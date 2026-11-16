/*
 * lazada_detail_dom.js
 * ---------------------------------------------------------------------------
 * Script thu thập CHI TIẾT sản phẩm Lazada, chạy trong Chrome thật của người dùng
 * (được Claude in Chrome nạp vào tab đang mở một trang sản phẩm lazada.vn).
 * Mục đích: học tập - đồ án DS111 (Phân tích dữ liệu), chạy chậm 8-20 giây/sản phẩm.
 *
 * Vì sao dùng cách này:
 *   - Bước 1 (lazada_scraper.py --listing-only) đã lấy 444 sản phẩm từ trang tìm kiếm.
 *   - Trang chi tiết lấy bằng Python/Playwright bị Lazada hiện captcha sau ~50 sản phẩm.
 *   - Script này chỉ ĐỌC PHẦN CHỮ HIỂN THỊ trên trang sản phẩm (danh mục, khối shop,
 *     điểm & số đánh giá, nhãn đánh giá, biến thể, bảng thông số, đổi trả/bảo hành),
 *     không gọi API nội bộ, không vượt captcha (gặp captcha -> tự dừng).
 *
 * Luồng chạy:
 *   1. __lzExtract(doc)   : đọc các khối thông tin từ DOM của 1 trang sản phẩm.
 *   2. __lzRun(ids, a, b) : lần lượt mở từng sản phẩm trong iframe cùng domain, chờ trang
 *                           hiển thị xong, gọi __lzExtract, nghỉ ngẫu nhiên a..b giây.
 *   3. __lzMaster(queue)  : chia hàng đợi thành đợt 40 sản phẩm; hết mỗi đợt tải về file
 *                           lazada_chitiet_bN.json (Downloads) rồi nghỉ 2-4 phút.
 *   4. Tiến độ lưu vào localStorage mỗi 10 giây -> bị ngắt thì chạy lại sẽ tiếp tục.
 *   5. Phía máy tính: merge_dom_details.py gộp từng file JSON vào data/raw/lazada_tai_nghe.csv.
 *
 * Cách dùng (trong console của 1 trang https://www.lazada.vn/products/...):
 *   __lzMaster(["2376425010", "2029577295", ...]);   // danh sách item_id cần lấy
 *   __lzState                                        // xem tiến độ
 *   __lzState.stop = true                            // dừng sau sản phẩm đang đọc
 */

// ---------- 1. Đọc dữ liệu hiển thị trên trang sản phẩm ----------
window.__lzExtract = function (doc) {
  const T = s => { const e = doc.querySelector(s); return e ? e.innerText.trim() : null; };
  const out = {};
  // Breadcrumb: Âm thanh > Các loại tai nghe > <loại tai nghe> > <tên SP> (bỏ phần tử cuối)
  const bc = [...doc.querySelectorAll('.breadcrumb_list li, .breadcrumb li')]
    .map(e => e.innerText.trim()).filter(Boolean);
  out.crumbs = bc.slice(0, -1);
  // Khối người bán: tên shop, % đánh giá tích cực, đã bán, số năm, phản hồi chat, giao nhanh...
  out.seller = T('.seller-container-v2, [class*="seller-container"]');
  // Điểm trung bình và số lượt đánh giá
  out.score = T('.score-average');
  out.title_count = T('.title-text');
  out.summary = T('.pdp-review-summary-v2');
  // Nhãn đánh giá: "Có hình/video(219) | Khách đã mua lại(13) | Âm thanh hay(59) ..."
  const rv = doc.querySelector('.summary'); let b = rv;
  for (let i = 0; i < 3 && b; i++) b = b.parentElement;
  out.review_tags = b ? b.innerText.split('\n').filter(t => /\(\d+\)$/.test(t.trim())).join(' | ') : null;
  // Bảng thông số kỹ thuật (key -> value), bỏ mã SKU
  const specs = {};
  doc.querySelectorAll('.specification-keys .key-li').forEach(li => {
    const k = li.querySelector('.key-title'), v = li.querySelector('.key-value');
    if (k && v) specs[k.innerText.trim()] = v.innerText.trim();
  });
  delete specs['SKU'];
  out.specs = specs;
  // Biến thể (màu sắc / phân loại)
  out.sku = [...doc.querySelectorAll('.sku-prop-v2')].map(e => e.innerText.replace(/\n/g, ' | ')).join(' || ');
  // Giao hàng (phí ship, thời gian dự kiến) và đổi trả / bảo hành / chính hãng
  out.delivery = T('.delivery-v2');
  out.service = T('[class*="warranty"], [class*="service-v2"], [class*="return-and-warranty"]');
  // Trạng thái đặc biệt
  out.redirect_app = /chuyển sang ứng dụng/i.test(doc.body.innerText.slice(0, 3000)); // SP chỉ xem trên app
  out.captcha = /punish|nc_1_n1z|slide to verify/i.test(doc.body.innerHTML.slice(0, 30000));
  return out;
};

// ---------- Hẹn giờ bằng Web Worker ----------
// Chrome bóp setTimeout của tab chạy nền xuống ~1 lần/phút; timer trong Worker không bị bóp
// -> script giữ đúng nhịp 8-20 s/sản phẩm ngay cả khi người dùng chuyển sang tab khác.
if (!window.__lzWorker) {
  const src = 'onmessage=e=>{const {id,ms}=e.data; setTimeout(()=>postMessage(id), ms);}';
  window.__lzWorker = new Worker(URL.createObjectURL(new Blob([src], { type: 'text/javascript' })));
  window.__lzWaits = {}; let n = 0;
  window.__lzWorker.onmessage = e => { const f = window.__lzWaits[e.data]; delete window.__lzWaits[e.data]; f && f(); };
  window.__lzSleep = ms => new Promise(r => { const id = ++n; window.__lzWaits[id] = r; window.__lzWorker.postMessage({ id, ms }); });
}

// ---------- Trạng thái + lưu tiến độ (resume) ----------
window.__lzResults = JSON.parse(localStorage.getItem('lzRes2') || '{}');
window.__lzSent = JSON.parse(localStorage.getItem('lzSent2') || '{}');
window.__lzState = { running: false, done: 0, last: null, stop: false, phase: 'idle' };
if (!window.__lzSaver) window.__lzSaver = setInterval(() => {
  try {
    localStorage.setItem('lzRes2', JSON.stringify(window.__lzResults));
    localStorage.setItem('lzSent2', JSON.stringify(window.__lzSent));
  } catch (e) { }
}, 10000);

// ---------- 2. Lấy lần lượt từng sản phẩm, nghỉ ngẫu nhiên minD..maxD giây ----------
window.__lzRun = async function (ids, minD, maxD) {
  const sleep = window.__lzSleep;
  window.__lzState.running = true;
  for (const id of ids) {
    if (window.__lzState.stop) break;          // đã gặp captcha -> dừng hẳn
    if (window.__lzResults[id]) continue;      // đã có -> bỏ qua (resume)
    // Mở trang sản phẩm trong iframe ẩn cùng domain www.lazada.vn
    const f = document.createElement('iframe');
    f.style.cssText = 'position:fixed;left:0;top:0;width:1300px;height:900px;opacity:0.01;pointer-events:none;z-index:-1';
    f.src = '/products/pdp-i' + id + '.html';
    document.body.appendChild(f);
    let res = { status: 'timeout' }; const t0 = Date.now(); let nullDoc = 0;
    while (Date.now() - t0 < 45000) {          // chờ tối đa 45 giây/sản phẩm (từ đợt 8; trước đó 30 s)
      await sleep(2000);
      try {
        const d = f.contentDocument;
        // Không đọc được document = trang bị chuyển sang domain khác (trang "mở app") -> app_only
        if (!d) { nullDoc++; if (nullDoc >= 5) { res = { status: 'app_only' }; break; } continue; }
        if (!d.body) continue;
        const w = f.contentWindow; w.scrollTo(0, d.body.scrollHeight / 2);   // cuộn để trang nạp phần dưới
        const r = window.__lzExtract(d);
        if (r.captcha) { res = { status: 'captcha' }; window.__lzState.stop = true; window.__lzState.captcha = true; break; }
        if (r.redirect_app) { res = { status: 'app_only' }; break; }
        const el = Date.now() - t0;
        // đủ: có khối shop + bảng thông số (sau 6 s), hoặc chỉ có khối shop sau 20 s (SP không có bảng thông số)
        if (r.seller && ((Object.keys(r.specs).length && el > 6000) || el > 20000)) {
          w.scrollTo(0, d.body.scrollHeight); await sleep(1500);
          res = Object.assign({ status: 'ok' }, window.__lzExtract(d));
          break;
        }
      } catch (e) { nullDoc++; if (nullDoc >= 5) { res = { status: 'app_only' }; break; } }
    }
    if (res.status === 'timeout') {             // hết giờ nhưng có một phần dữ liệu -> giữ lại
      try { const r = window.__lzExtract(f.contentDocument); if (r.seller) res = Object.assign({ status: 'ok_partial' }, r); } catch (e) { }
    }
    if (res.status !== 'captcha') window.__lzResults[id] = res;
    window.__lzState.done++; window.__lzState.last = id + ':' + res.status;
    f.remove();
    await sleep((minD + Math.random() * (maxD - minD)) * 1000);   // nghỉ ngẫu nhiên
  }
  window.__lzState.running = false;
};

// ---------- Tải về file JSON chứa các kết quả mới (chưa xuất) ----------
window.__lzDownloadNew = function (name) {
  const out = {};
  for (const [k, v] of Object.entries(window.__lzResults)) if (!window.__lzSent[k]) { out[k] = v; window.__lzSent[k] = 1; }
  if (!Object.keys(out).length) return 0;
  const blob = new Blob([JSON.stringify(out)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 5000);
  localStorage.setItem('lzSent2', JSON.stringify(window.__lzSent));
  return Object.keys(out).length;
};

// ---------- 3. Điều phối: đợt 40 sản phẩm, xuất file, nghỉ 2-4 phút ----------
window.__lzMaster = async function (q) {
  const sleep = window.__lzSleep;
  let batch = parseInt(localStorage.getItem('lzBatch2') || '1');
  for (let i = 0; i < q.length; i += 40) {
    if (window.__lzState.stop) break;
    const chunk = q.slice(i, i + 40).filter(id => !window.__lzResults[id]);
    if (!chunk.length) continue;
    window.__lzState.phase = 'batch ' + batch;
    await window.__lzRun(chunk, 8, 20);
    window.__lzDownloadNew('lazada_chitiet_b' + batch + '.json');
    batch++; localStorage.setItem('lzBatch2', String(batch));
    if (window.__lzState.stop) break;
    if (i + 40 < q.length) { window.__lzState.phase = 'pause'; await sleep((120 + Math.random() * 120) * 1000); }
  }
  const reason = window.__lzState.captcha ? 'captcha' : (window.__lzState.stop ? 'stopped' : 'done');  // stopped = người dùng chủ động dừng
  window.__lzDownloadNew('lazada_chitiet_b' + batch + '_final.json');
  window.__lzState.phase = 'finished:' + reason;
  // File trạng thái cuối để phía máy tính biết đã xong / dừng vì captcha
  const blob = new Blob([JSON.stringify({ reason, total: Object.keys(window.__lzResults).length, last: window.__lzState.last })], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'lazada_chitiet_STATUS_' + reason + '.json'; document.body.appendChild(a); a.click();
};
