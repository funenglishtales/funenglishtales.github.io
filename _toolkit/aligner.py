# -*- coding: utf-8 -*-
"""aligner.py — khớp chữ với giọng bằng máy nhận dạng giọng nói offline (sherpa-onnx). Fun English Tales Word Practice.

Cách làm: máy nhận dạng giọng nói (sherpa-onnx, chạy offline) nghe file mp3 và trả về MỐC GIỜ CỦA TỪNG CHỮ
nó nghe được -> đối chiếu với văn bản người dùng đưa (so khớp chuỗi chữ) -> chữ khớp lấy đúng mốc giờ thật,
chữ không khớp được nội suy giữa 2 chữ khớp gần nhất -> tinh chỉnh đầu/cuối câu theo năng lượng giọng (hội thoại).
Kết quả kèm báo cáo độ khớp từng dòng để biết dòng nào còn đáng ngờ.

Ngôn ngữ: en (NeMo Parakeet TDT 0.6B v2) · vi (Zipformer tiếng Việt). Ngôn ngữ khác -> trả None (build dùng bản nháp).
"""
import os, re, subprocess, difflib, unicodedata
import numpy as np

SR = 16000
MDIR = os.environ.get("FET_MODELS", os.path.expanduser("~/models"))
MODELS = {
    "en": ("sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8", "nemo_transducer",
           "encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", 55),
    "vi": ("sherpa-onnx-zipformer-vi-int8-2025-04-20", "",
           "encoder-epoch-12-avg-8.int8.onnx", "decoder-epoch-12-avg-8.onnx", "joiner-epoch-12-avg-8.int8.onnx", 18),
}

def model_ready(lang):
    if lang not in MODELS:
        return False
    try:
        import sherpa_onnx  # noqa
    except Exception:
        return False
    return os.path.isfile(os.path.join(MDIR, MODELS[lang][0], "tokens.txt"))

# ------------------------------------------------------------------ âm thanh
def load(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                       capture_output=True)
    return np.frombuffer(r.stdout, np.float32).copy()

def voice_band(x):
    """Bài hát có nhạc nền: giữ dải giọng 120–5000 Hz để máy nghe giọng rõ hơn."""
    from scipy.signal import butter, sosfilt
    return sosfilt(butter(4, [120, 5000], btype="band", fs=SR, output="sos"), x).astype(np.float32)

def energy(x, hop=0.01):
    h = int(SR * hop); n = len(x) // h
    db = 20 * np.log10(np.sqrt(np.mean(x[:n * h].reshape(n, h) ** 2, axis=1) + 1e-12) + 1e-9)
    return np.convolve(db, np.ones(5) / 5, mode="same")

def chunks(x, maxlen):
    """Cắt audio thành các đoạn ≤ maxlen giây, cắt đúng chỗ im lặng nhất (không cắt ngang chữ)."""
    db = energy(x); out = []; a = 0.0; N = len(x) / SR
    while N - a > maxlen:
        lo, hi = int((a + maxlen * 0.6) * 100), int((a + maxlen) * 100)
        cut = (lo + int(np.argmin(db[lo:hi]))) / 100
        out.append((a, cut)); a = cut
    out.append((a, N))
    return out

# ------------------------------------------------------------------ nhận dạng
_REC = {}
def recognizer(lang):
    if lang in _REC:
        return _REC[lang]
    import sherpa_onnx
    sub, mt, e, de, j, maxlen = MODELS[lang]
    d = os.path.join(MDIR, sub) + "/"
    kw = dict(encoder=d + e, decoder=d + de, joiner=d + j, tokens=d + "tokens.txt",
              num_threads=max(1, min(4, os.cpu_count() or 2)))
    if mt:
        kw["model_type"] = mt
    _REC[lang] = sherpa_onnx.OfflineRecognizer.from_transducer(**kw)
    return _REC[lang]

def asr_words(x, lang):
    rec = recognizer(lang); maxlen = MODELS[lang][5]
    words = []
    for a, b in chunks(x, maxlen):
        seg = x[int(a * SR):int(b * SR)]
        if len(seg) < SR * 0.3:
            continue
        s = rec.create_stream()
        s.accept_waveform(SR, np.concatenate([seg, np.zeros(int(SR * 0.3), np.float32)]))
        rec.decode_stream(s); r = s.result
        durs = list(getattr(r, "durations", []) or [])
        first = True
        for k, (tok, ts) in enumerate(zip(r.tokens, r.timestamps)):
            dur = durs[k] if k < len(durs) and durs[k] > 0 else 0.08
            new = tok.startswith(" ") or tok.startswith("▁") or first
            t = tok.replace("▁", " ").strip()
            if not t or not re.search(r"[\w'’]", t):
                continue  # bỏ dấu câu: không để dấu câu kéo dài chữ
            if new:
                words.append({"w": t, "s": a + ts, "e": a + ts + dur})
            else:
                words[-1]["w"] += t; words[-1]["e"] = a + ts + dur
            first = False
    return [w for w in words if norm(w["w"])]

# ------------------------------------------------------------------ so khớp chữ
NUM = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven",
       "8": "eight", "9": "nine", "10": "ten", "11": "eleven", "12": "twelve", "15": "fifteen", "20": "twenty",
       "30": "thirty", "40": "forty", "45": "forty five", "50": "fifty", "100": "hundred"}

def norm(w):
    w = unicodedata.normalize("NFC", w.lower()).replace("’", "'")
    return re.sub(r"[^\w']", "", w).strip("'")

def expand(asr):
    """'8:30' -> 'eight' 'thirty'; giữ khoảng thời gian, chia đều cho các chữ con."""
    out = []
    for w in asr:
        if re.search(r"\d", w["w"]):
            parts = [p for p in re.split(r"[:\-./]", w["w"]) if p]
            toks = " ".join(NUM.get(re.sub(r"\D", "", p).lstrip("0") or "0", p) for p in parts).split()
        else:
            toks = [w["w"]]
        dt = (w["e"] - w["s"]) / max(1, len(toks))
        for i, t in enumerate(toks):
            out.append({"w": t, "s": w["s"] + i * dt, "e": w["s"] + (i + 1) * dt})
    return out

def align_words(text_words, asr):
    """-> [[start, end, độ_tin]] cho từng chữ văn bản. độ_tin: 1 khớp đúng · 0.5 khớp gần · 0 nội suy."""
    asr = expand(asr)
    A = [norm(w) for w in text_words]; B = [norm(w["w"]) for w in asr]
    res = [None] * len(A)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, A, B, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                b = asr[j1 + k]; res[i1 + k] = [b["s"], b["e"], 1.0]
        elif tag == "replace":
            s, e = asr[j1]["s"], asr[j2 - 1]["e"]; n = i2 - i1
            near = 0.5 if abs((i2 - i1) - (j2 - j1)) <= 1 else 0.25
            for k in range(n):
                res[i1 + k] = [s + (e - s) * k / n, s + (e - s) * (k + 1) / n, near]
    idx = [i for i, r in enumerate(res) if r]
    if not idx:
        return None
    for i in range(len(res)):
        if res[i]:
            continue
        p = max([j for j in idx if j < i], default=None); q = min([j for j in idx if j > i], default=None)
        if p is None:
            res[i] = [max(0, res[q][0] - 0.3 * (q - i)), max(0.05, res[q][0] - 0.3 * (q - i - 1)), 0.0]
        elif q is None:
            res[i] = [res[p][1] + 0.3 * (i - p - 1), res[p][1] + 0.3 * (i - p), 0.0]
        else:
            s, e = res[p][1], res[q][0]; n = q - p
            res[i] = [s + (e - s) * (i - p - 1) / max(1, n - 1), s + (e - s) * (i - p) / max(1, n - 1), 0.0]
    for i in range(len(res) - 1):          # chữ sau không được bắt đầu trước chữ trước
        if res[i + 1][0] < res[i][0] + 0.02:
            res[i + 1][0] = res[i][0] + 0.02
        res[i][1] = max(res[i][0] + 0.05, min(res[i][1], res[i + 1][0] + 0.25))
    return res

# ------------------------------------------------------------------ tinh chỉnh đầu/cuối câu (giọng nói)
def refine(x, res, firsts, lasts):
    db = energy(x); lo, hi = np.percentile(db, 10), np.percentile(db, 97)
    on_thr, off_thr = lo + 0.35 * (hi - lo), lo + 0.30 * (hi - lo)
    for i in firsts:
        t = res[i][0]; a, b = max(0, int((t - 0.35) * 100)), min(len(db) - 1, int((t + 0.35) * 100))
        above = np.where(db[a:b] > on_thr)[0]
        if len(above):
            on = (a + above[0]) / 100
            if on < res[i][1] - 0.05:
                res[i][0] = on
    nexts = [res[i][0] for i in firsts[1:]] + [None]
    for i, nx in zip(lasts, nexts):
        t = res[i][1]; a = max(int(res[i][0] * 100) + 1, int((t - 0.5) * 100)); b = int((t + 0.4) * 100)
        if nx is not None:
            b = min(b, int((nx - 0.03) * 100))
        b = min(b, len(db) - 1)
        if b > a:
            above = np.where(db[a:b] > off_thr)[0]
            if len(above):
                res[i][1] = (a + above[-1] + 1) / 100 + 0.05
    return res

def snap_to_voice(x, res):
    """Chữ nào bị máy đặt mốc vào chỗ IM LẶNG (lỗi hay gặp ở chữ đầu mỗi đoạn) -> dời tới chỗ giọng cất lên."""
    db = energy(x); lo, hi = np.percentile(db, 10), np.percentile(db, 97); thr = lo + 0.30 * (hi - lo)
    voiced = db > thr; n = len(voiced)
    for i, r in enumerate(res):
        a = int(r[0] * 100)
        if a >= n or voiced[min(n - 1, a):min(n, a + 15)].any():
            continue                      # đã nằm trên/sát tiếng nói
        limit = int(res[i + 1][0] * 100) if i + 1 < len(res) else n
        nxt = np.where(voiced[a:max(a, min(n, limit))])[0]
        if len(nxt):
            new = (a + nxt[0]) / 100
            r[1] = max(r[1] + (new - r[0]), new + 0.08) if r[1] <= new else r[1]
            r[0] = new
    return res

# ------------------------------------------------------------------ hàm chính
def align_lines(audio_path, lines, lang, mode="conv"):
    """lines: [[chữ, chữ, ...], ...] (chữ hiển thị, đã bỏ tên người nói)
    -> {'lines': [[[start,end],...] mỗi chữ], 'line_conf': [...], 'matched': x, 'total': n,
        'asr_text': '...', 'method': 'asr-<lang>'}  hoặc None nếu không có mô hình."""
    if not model_ready(lang):
        return None
    x = load(audio_path)
    xa = voice_band(x) if mode == "song" else x
    asr = asr_words(xa, lang)
    flat = [w for l in lines for w in l]
    res = align_words(flat, asr)
    if res is None:
        return {"lines": None, "matched": 0, "total": len(flat), "asr_text": "", "method": "asr-" + lang}
    firsts, lasts, k = [], [], 0
    for l in lines:
        firsts.append(k); lasts.append(k + len(l) - 1); k += len(l)
    if mode != "song":
        res = snap_to_voice(x, res)
        res = refine(x, res, firsts, lasts)
    out, conf, k = [], [], 0
    for l in lines:
        seg = res[k:k + len(l)]; k += len(l)
        out.append([[round(a, 3), round(b, 3)] for a, b, _ in seg])
        conf.append(round(sum(c for _, _, c in seg) / max(1, len(seg)), 2))
    return {"lines": out, "line_conf": conf, "matched": sum(1 for r in res if r[2] == 1.0), "total": len(flat),
            "asr_text": " ".join(w["w"] for w in asr), "method": "asr-" + lang}
