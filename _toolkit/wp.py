# -*- coding: utf-8 -*-
"""wp.py — Fun English Tales · Word Practice: tạo trang luyện từ vựng cho 1 tập.

QUY TRÌNH 2 BƯỚC (giữa 2 bước, Claude viết content.json):

  1) prepare — canh khớp chữ–giọng toàn tập, cắt câu phim chứa từng từ mới, nghe lại để kiểm tra
     python3 wp.py prepare --ep 8 --title "Grandpa's Secret Recipe" --mp3 tap08.mp3 \
         --script TRICH_VOICE_Tap08.txt --vocab Buoc6_Tap08.txt --yt https://youtu.be/XXXX \
         [--thumb thumbnail.png] --work work/ep08
     -> work/ep08/words.json, clips/, report.txt, content_todo.json (khung để Claude điền)

  2) (Claude) viết work/ep08/content.json theo content_todo.json — xem SKILL.md

  3) build — tạo giọng đọc, dựng trang web (thư mục epNN cho GitHub Pages) + 1 file HTML độc lập (gửi Zalo)
     python3 wp.py build --work work/ep08 --site site_repo
     -> site_repo/ep08/ (index.html + audio/*.json + img/), site_repo/index.html (thêm/cập nhật thẻ tập),
        work/ep08/out/FunEnglishTales_TapNN_WordPractice.html

Mô hình: bash setup_models.sh en tts  (một lần mỗi phiên, tải từ GitHub releases của k2-fsa/sherpa-onnx)
"""
import argparse, base64, difflib, html, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
esc = lambda s: html.escape(s, quote=True)

# ---------- 1. lời thoại ----------
NAMES = {"BROTHER": "Leo", "SISTER": "Mia", "MOM": "Mom", "DAD": "Dad", "GRANDPA": "Grandpa",
         "GRANDMA": "Grandma", "BUDDY": "Buddy", "DOG": "Buddy"}
CODE_RE = re.compile(r'^\[([A-Z0-9_]+)\]:\s*"(.*?)"\s*(.*)$')


def parse_script(path):
    """File TRICH_VOICE: 'Scene 0001: ...'; lời nhân vật dạng [GRANDPA_V1]: "..." (trước/sau có thể kèm lời kể).
    - Scene phụ kiểu 0092B được gộp vào scene 92; ghi chú trong ngoặc (BỔ SUNG...) bị bỏ.
    - Lời trong ngoặc kép không ghi tên -> người nói 'Character'."""
    scenes = []
    for raw in open(path, encoding="utf-8-sig"):
        m = re.match(r"^\s*Scene\s+(\d+)([A-Za-z]?)\s*(?:\([^)]*\))?\s*:\s*(.*)$", raw.strip())
        if not m:
            continue
        n, sub = int(m.group(1)), m.group(2)
        body = re.sub(r"\s+", " ", m.group(3).replace("“", '"').replace("”", '"')).strip()
        body = re.sub(r"^\([^)]*[^\x00-\x7f][^)]*\)\s*", "", body)     # ghi chú tiếng Việt đầu dòng
        lines = []
        pos = 0
        for c in re.finditer(r'\[([A-Z0-9_]+)\]:\s*"(.*?)"', body):
            pre = body[pos:c.start()].strip()
            if pre:
                lines.append(("Narrator", pre))
            code = re.sub(r"\d+$", "", c.group(1).split("_")[0])
            lines.append((NAMES.get(code, code.title()), c.group(2).strip()))
            pos = c.end()
        rest = body[pos:].strip()
        if rest:
            if re.fullmatch(r'"[^"]+"', rest):
                lines.append(("Character", rest.strip('"').strip()))
            else:
                lines.append(("Narrator", rest.strip('"').strip() if rest.count('"') == 2 and rest.startswith('"') and rest.endswith('"') else rest))
        if sub and scenes and scenes[-1][0] == n:
            scenes[-1][1].extend(lines); continue
        if any(x[0] == n for x in scenes):
            continue                     # scene trùng số (file prompt lặp dòng) -> giữ lần đầu
        scenes.append([n, lines])
    if not scenes:
        sys.exit("NO_SCENES: không đọc được dòng 'Scene NNNN:' nào trong file lời thoại.")
    return scenes


# ---------- 2. danh sách từ mới (Bước 6) ----------
POS_RE = re.compile(r"\s*\((n|v|adj|adv|phr|phrase|phrasal verb|idiom|noun|verb|adjective|adverb)\.?\)\s*$", re.I)


def parse_vocab(path):
    """Bảng markdown Bước 6. Cột: # | Scene | Từ (nguyên mẫu) [+ loại từ] | Nghĩa tiếng Anh | (Nghĩa TV) | Câu VO.
    Chấp nhận bảng 5 cột (cũ) và 6 cột (mới)."""
    out = []
    for raw in open(path, encoding="utf-8-sig"):
        c = [x.strip() for x in raw.strip().strip("|").split("|")]
        if len(c) >= 4 and c[0].isdigit() and re.match(r"^\d+$", c[1]):
            word = c[2].strip(" *")
            pos = ""
            m = POS_RE.search(word)
            if m:
                pos = m.group(1).lower(); word = word[:m.start()].strip()
            vi = c[4] if len(c) >= 6 else ""
            vo = (c[5] if len(c) >= 6 else c[4]).strip().strip('"“”').strip()
            out.append(dict(word=word, pos=pos, meaning=c[3].strip(), vi=vi, scene=int(c[1]), vo=vo))
    if not out:   # dạng cũ: "SCENE | TỪ VỰNG | GHI CHÚ" (không có nghĩa tiếng Anh, không có câu VO)
        for raw in open(path, encoding="utf-8-sig"):
            c = [x.strip() for x in raw.strip().strip("|").split("|")]
            if len(c) >= 2 and re.match(r"^\d{3,4}$", c[0]):
                out.append(dict(word=c[1].replace("*", "").strip(), pos="", meaning="", vi="", scene=int(c[0]), vo="",
                                note=c[2] if len(c) > 2 else ""))
    if not out:
        sys.exit("NO_VOCAB: không đọc được bảng từ vựng trong file Bước 6.")
    return out


SELF_RE2 = re.compile(r"(?:^|[.!?\"]\s*)An?\s+([a-z]+) is (someone|something|a person|a place) (who|that|where) ([^—.!?\"]+)")
SELF_RE = re.compile(r"(?:^|[.!?\"]\s*)(?:An?\s+|To\s+)?([A-Za-z][a-z-]+) means ([^—.]+)")


def self_explained(scenes, have):
    """Câu VO tự giải nghĩa 'X means Y' -> thêm X vào danh sách (nếu chưa có)."""
    out = []
    for n, ls in scenes:
        for sp, tx in ls:
            for m2 in SELF_RE2.finditer(tx):
                w = m2.group(1).lower()
                if w not in have and w not in [o["word"] for o in out]:
                    out.append(dict(word=w, pos="", meaning=("%s %s %s." % (m2.group(2), m2.group(3), m2.group(4).strip())).capitalize(),
                                    vi="", scene=n, selfx=True))
            for m in SELF_RE.finditer(tx):
                w = m.group(1).lower()
                if w in ("that", "this", "it", "which", "what", "he", "she", "which"):
                    continue
                if w not in have and w not in [o["word"] for o in out]:
                    out.append(dict(word=w, pos="", meaning=m.group(2).strip().capitalize().rstrip(",") + ".",
                                    vi="", scene=n, selfx=True))
    return out


# ---------- 3. canh khớp toàn tập ----------
def align_episode(mp3, scenes):
    import aligner
    if not aligner.model_ready("en"):
        sys.exit("NO_MODEL: chạy  bash setup_models.sh en tts  trước.")
    lines, meta = [], []
    for n, ls in scenes:
        for sp, tx in ls:
            if tx.split():
                lines.append(tx.split()); meta.append((n, sp, tx))
    al = aligner.align_lines(mp3, lines, "en", "conv")
    if not al or al["lines"] is None:
        sys.exit("ALIGN_FAIL: máy nhận dạng không nghe được audio này.")
    out = [dict(scene=n, sp=sp, text=tx, conf=al["line_conf"][i],
                w=[[w, s, e] for w, (s, e) in zip(lines[i], al["lines"][i])]) for i, (n, sp, tx) in enumerate(meta)]
    return out, al["matched"], al["total"]


# ---------- 4. cắt câu phim + kiểm tra ----------
key = lambda s: re.sub(r"[^a-z' -]", "", s.lower())
normw = lambda s: [re.sub(r"[^a-z0-9']", "", x) for x in s.lower().replace("—", " ").replace("-", "").split()
                   if re.sub(r"[^a-z0-9']", "", x)]


def word_re(c):
    """Regex nhận mọi dạng của từ: dạng gốc (+ đuôi biến đổi) hoặc đúng dạng trong phim (in_ep, kể cả bất quy tắc)."""
    alts = [stem_re(c["base"])]
    if c.get("in_ep"):
        alts.append(re.escape(c["in_ep"]))
    return "(?:" + "|".join(alts) + r")\b" if " " in c["base"] else "(?:" + "|".join(alts) + ")"


def stem_re(base):
    if " " in base or "-" in base:
        return re.escape(base)
    s = base[:-1] if len(base) > 4 and base.endswith("e") else base
    if len(s) > 3 and s.endswith("y"):
        s = s[:-1]
    return re.escape(s) + r"\w*"


def cut_clips(mp3, lines, vocab, work):
    import aligner
    os.makedirs(os.path.join(work, "clips"), exist_ok=True)
    out, rep = [], []
    for v in vocab:
        rx = re.compile(r"\b" + stem_re(v["word"].split()[0].lower()), re.I)
        full = re.compile(r"\b" + stem_re(v["word"].lower()), re.I) if " " in v["word"] or "-" in v["word"] else rx
        # tìm câu chứa từ ở đúng scene, không có thì tìm scene gần nhất (±8) — bảng Bước 6 cũ có thể lệch số scene
        # ưu tiên câu video nói đúng (khớp ≥ 80%), rồi tới scene gần nhất; ±8 scene trước, không có thì cả tập
        rank = lambda l: (l["conf"] < 0.8, abs(l["scene"] - v["scene"]))
        near = sorted((l for l in lines if abs(l["scene"] - v["scene"]) <= 8 and full.search(l["text"])), key=rank) or \
               sorted((l for l in lines if full.search(l["text"])), key=rank)
        if not near:
            rep.append("KHÔNG CÓ TRONG LỜI  %-18s (Bước 6 ghi scene %d: \"%s\") — từ này không có trong lời thoại tập" %
                       (v["word"], v["scene"], v.get("vo", "")[:60]))
            out.append(dict(v, sp="Narrator", text=v.get("vo", ""), conf=0, source="absent")); continue
        pick = near[0]
        if pick["scene"] != v["scene"]:
            rep.append("LỆCH SCENE %-16s Bước 6 ghi %d, lời thoại ở scene %d" % (v["word"], v["scene"], pick["scene"]))
            v = dict(v, scene=pick["scene"])
        sents, cur = [], []
        for w in pick["w"]:
            cur.append(w)
            if re.search(r"[.!?]$", w[0]):
                sents.append(cur); cur = []
        if cur:
            sents.append(cur)
        ws = next((x for x in sents if rx.search(" ".join(t[0] for t in x))), pick["w"])
        text = " ".join(t[0] for t in ws)
        rec = dict(v, sp=pick["sp"], text=text, conf=pick["conf"], source="tts")
        if not rx.search(text):
            rep.append("CẢNH BÁO %-16s không thấy từ trong câu VO scene %d: %s" % (v["word"], v["scene"], text[:70]))
        if pick["conf"] >= 0.8:
            a = max(0.0, ws[0][1] - 0.04); b = ws[-1][2] + 0.18
            f = "clips/s%03d_%s.mp3" % (v["scene"], re.sub(r"\W+", "-", v["word"]))
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "%.3f" % a, "-to", "%.3f" % b, "-i", mp3,
                            "-ac", "1", "-c:a", "libmp3lame", "-b:a", "64k", os.path.join(work, f)], check=True)
            heard = " ".join(w["w"] for w in aligner.asr_words(aligner.load(os.path.join(work, f)), "en"))
            r = difflib.SequenceMatcher(None, normw(text), normw(heard)).ratio()
            if r >= 0.7:
                rec.update(source="episode", clip=f, words=[[w, round(x - a, 2), round(y - a, 2)] for w, x, y in ws],
                           check=round(r, 2))
            else:
                rep.append("GIỌNG TẠO %-15s scene %d: đoạn phim nghe ra khác lời (%.0f%%): %s" % (v["word"], v["scene"], r * 100, heard[:70]))
        else:
            rep.append("GIỌNG TẠO %-15s scene %d: video không nói đúng câu trong kịch bản (khớp %.0f%%)" % (v["word"], v["scene"], pick["conf"] * 100))
        out.append(rec)
    return out, rep


def cmd_prepare(a):
    work = a.work
    os.makedirs(work, exist_ok=True)
    mp3 = os.path.join(work, "episode.mp3")
    shutil.copy(a.mp3, mp3) if os.path.abspath(a.mp3) != os.path.abspath(mp3) else None
    scenes = parse_script(a.script)
    vocab = parse_vocab(a.vocab)
    vocab += self_explained(scenes, {v["word"].lower() for v in vocab})
    vocab.sort(key=lambda v: v["scene"])
    print("Lời thoại: %d scene · Từ mới: %d (%d tự giải nghĩa)" % (len(scenes), len(vocab), sum(1 for v in vocab if v.get("selfx"))), flush=True)
    print("Đang canh khớp toàn tập (vài phút)...", flush=True)
    lines, m, t = align_episode(mp3, scenes)
    print("Khớp toàn tập: %d/%d chữ (%.0f%%)" % (m, t, m / t * 100), flush=True)
    words, rep = cut_clips(mp3, lines, vocab, work)
    if a.thumb:
        from PIL import Image
        im = Image.open(a.thumb).convert("RGB"); im.thumbnail((720, 720)); im.save(os.path.join(work, "thumb.jpg"), quality=78)
    meta = dict(ep=int(a.ep), title=a.title, yt=a.yt or "", question=a.question or "")
    json.dump(meta, open(os.path.join(work, "meta.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(words, open(os.path.join(work, "words.json"), "w"), ensure_ascii=False, indent=1)
    weak = [l for l in lines if l["conf"] < 0.6]
    todo = {v["word"]: {"base": v["word"], "pos": v["pos"] or "?", "in_ep": "(dạng trong phim nếu khác nguyên mẫu, không thì xoá)",
                        "pic": "2 emoji", "ex": [["câu đời sống 1", "giải nghĩa đơn giản", "mô tả ảnh"],
                                                 ["câu đời sống 2", "giải nghĩa đơn giản", "mô tả ảnh"]],
                        "_meaning": v["meaning"], "_movie": v["text"]} for v in words}
    json.dump(todo, open(os.path.join(work, "content_todo.json"), "w"), ensure_ascii=False, indent=1)
    lines_rep = ["TẬP %s · %s" % (a.ep, a.title), "Khớp toàn tập: %d/%d chữ (%.0f%%)" % (m, t, m / t * 100),
                 "Từ mới: %d · câu phim giọng thật: %d · giọng tạo: %d" % (len(words), sum(1 for w in words if w["source"] == "episode"),
                                                                       sum(1 for w in words if w["source"] != "episode")), ""] + rep
    if weak:
        lines_rep += ["", "Scene có lời trong video KHÁC kịch bản (khớp < 60%) — chỉ ảnh hưởng nếu có từ mới ở đó:"] + \
                     ["  scene %d (%s): %s" % (l["scene"], l["sp"], l["text"][:70]) for l in weak]
    open(os.path.join(work, "report.txt"), "w", encoding="utf-8").write("\n".join(lines_rep) + "\n")
    print("\n".join(lines_rep))
    print("PREPARE_OK %s · tiếp theo: viết %s/content.json rồi chạy build" % (work, work))


# ---------- 5. giọng đọc (Kokoro) ----------
class TTS:
    def __init__(self):
        import onnxruntime as ort, sherpa_onnx
        K = os.path.join(os.environ.get("FET_MODELS", os.path.expanduser("~/models")), "kokoro-multi-lang-v1_0")
        if not os.path.exists(os.path.join(K, "voices.bin")):
            sys.exit("NO_TTS_MODEL: chạy  bash setup_models.sh tts  trước.")
        names = ort.InferenceSession(os.path.join(K, "model.onnx"), providers=["CPUExecutionProvider"]) \
            .get_modelmeta().custom_metadata_map["speaker_names"].split(",")
        self.sid = {n: i for i, n in enumerate(names)}
        self.t = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(model=os.path.join(K, "model.onnx"), voices=os.path.join(K, "voices.bin"),
                tokens=os.path.join(K, "tokens.txt"), data_dir=os.path.join(K, "espeak-ng-data"), dict_dir=os.path.join(K, "dict"),
                lexicon=os.path.join(K, "lexicon-us-en.txt") + "," + os.path.join(K, "lexicon-zh.txt")), num_threads=4)))

    def say(self, text, voice, out, speed=0.92):
        import numpy as np, soundfile as sf
        g = self.t.generate(text, sid=self.sid[voice], speed=speed)
        x = np.asarray(g.samples, np.float32)
        x = np.concatenate([np.zeros(int(g.sample_rate * .12), np.float32), x, np.zeros(int(g.sample_rate * .2), np.float32)])
        x = x / max(1e-6, np.abs(x).max()) * 0.9
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        sf.write(tmp, x, g.sample_rate)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tmp, "-ac", "1", "-b:a", "48k", out], check=True)
        os.unlink(tmp)


MALE = {"Leo", "Dad", "Grandpa"}


# ---------- 6. dựng trang ----------
def mark(sentence, pat, cls="hl"):
    m = re.search(r"\b" + pat, sentence, re.I)
    if not m:
        return esc(sentence), None
    return esc(sentence[:m.start()]) + '<mark class="%s">' % cls + esc(m.group(0)) + "</mark>" + esc(sentence[m.end():]), m.group(0)


def render(work, W, C, meta, audio, thumb_src):
    cards, quiz, chips = [], [], []
    for i, v in enumerate(W):
        c = C[v["word"]]
        wid = "w%02d" % i
        base = c["base"]
        if v["source"] == "episode":
            rx = re.compile(r"\b" + word_re(c), re.I)
            parts = base.lower().split()
            toks = []
            for w, s, e in v["words"]:
                kw = bool(rx.search(w)) or (len(parts) > 1 and w.lower().strip(",.!?") in parts)
                toks.append('<span class="tk%s" data-s="%.2f" data-e="%.2f">%s</span>' % (" kw" if kw else "", s, e, esc(w)))
            movie, note = " ".join(toks), "From the episode"
        else:
            movie = mark(v["text"], word_re(c))[0]
            note = "Example sentence" if v["source"] == "absent" else "Read aloud for practice"
        exs = []
        for j, (sent, expl, _d) in enumerate(c["ex"]):
            h, form = mark(sent, word_re(c))
            exs.append('<li class="ex"><button class="play sm" type="button" data-a="e%02d_%d" aria-label="Listen to this sentence">'
                       '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg></button>'
                       '<div><p class="en">%s</p><p class="mean"><span>What it means:</span> %s</p></div></li>' % (i, j, h, esc(expl)))
            if form:
                quiz.append({"q": re.sub(r"\b" + word_re(c), "_____", sent, count=1, flags=re.I), "a": form, "w": i})
        in_ep = ('<span class="form">in the episode: <b>%s</b></span>' % esc(c["in_ep"])) if c.get("in_ep") and v["source"] != "absent" else ""
        cards.append(f'''
<article class="card" id="{wid}">
  <div class="pic" aria-hidden="true">{esc(c.get("pic", ""))}</div>
  <div class="body">
    <header class="head">
      <span class="num">{i + 1:02d}</span>
      <h3>{esc(base)}</h3>
      <button class="say" type="button" data-a="w{i:02d}" aria-label="Hear the word {esc(base)}">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4zm12.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4z"/></svg></button>
      {('<span class="ipa">' + esc(c["ipa"]) + '</span>') if c.get("ipa") else ""}
      <span class="pos">{esc(c.get("pos", ""))}</span>{in_ep}
    </header>
    <p class="def">{esc(v["meaning"])}</p>
    <section class="movie">
      <div class="mhead"><span class="tag">{note}</span>{"" if v["source"] == "absent" else '<span class="spk sp-%s">%s</span><span class="scene">Scene %d</span>' % (v["sp"].lower(), esc(v["sp"]), v["scene"])}</div>
      <p class="line" data-line="m{i:02d}">{movie}</p>
      <div class="ctl">
        <button class="play" type="button" data-a="m{i:02d}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>Listen</button>
        <button class="play ghost" type="button" data-a="m{i:02d}" data-rate="0.75"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>Slow</button>
        <span class="tip">Then pause and say it out loud.</span>
      </div>
    </section>
    <section class="life">
      <h4>Use it in real life</h4>
      <ul>{"".join(exs)}</ul>
    </section>
    <label class="done"><input type="checkbox" id="done-{wid}" data-w="{wid}"> I can use this word</label>
  </div>
</article>''')
        chips.append('<a class="chip" href="#%s" data-w="%s">%s</a>' % (wid, wid, esc(base)))
    page = open(os.path.join(HERE, "page_template.html"), encoding="utf-8").read()
    if len(cards) >= 8:
        cards.insert(len(cards) // 2, "\n" + cta_box("mid", meta["yt"]))
    rep = {"__CTA_TOP__": cta_box("top", meta["yt"]), "__CTA_END__": cta_box("end", meta["yt"]),
           "__TITLE__": esc(meta["title"]), "__EP__": str(meta["ep"]), "__N__": str(len(W)), "__YT__": esc(meta["yt"]),
           "__THUMB__": thumb_src, "__CHIPS__": "".join(chips), "__CARDS__": "".join(cards), "__QUESTION__": esc(meta.get("question", "")),
           "__AUD__": json.dumps(audio), "__QUIZ__": json.dumps(quiz, ensure_ascii=False).replace("</", "<\\/")}
    for k, val in rep.items():
        page = page.replace(k, val)
    return page, len(quiz)


def wrap(body, desc):
    title = re.search(r"<title>(.*?)</title>", body).group(1)
    head = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<meta name="theme-color" content="#121F55">\n<meta name="description" content="%s">\n'
            '<meta property="og:type" content="website">\n<meta property="og:title" content="%s · Fun English Tales">\n'
            '<meta property="og:description" content="%s">\n'
            '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}img{max-width:100%%}[hidden]{display:none!important}</style>\n'
            % (esc(desc), title, esc(desc)))
    body = body.replace('<header class="band">', '</head>\n<body>\n<header class="band">', 1)
    return head + body + "\n</body>\n</html>\n"


def cta_box(kind, yt):
    """Khung 'Your turn' kêu gọi bình luận — đặt ở đầu, giữa danh sách và cuối trang."""
    head = {"top": ("Use a word, share your sentence", "Learn a word below, then use it in a sentence about your own life and post it under the episode. We read them all!"),
            "mid": ("Halfway there! Try one word now", "Pick a word you just practised and write your own sentence in the YouTube comments."),
            "end": ("Your turn: write a sentence", "Pick one word from today and use it in a sentence about your own life. Post it in the comments under the episode. We read them all!")}[kind]
    mini = "" if kind == "end" else " mini"
    return ('<section class="cta%s" aria-label="Write a sentence in the comments"><h2>%s</h2><p>%s</p>'
            '<div class="tpl"><code>My word is "_____": ______________________</code><button class="btn copy" type="button">Copy</button></div>'
            '<div class="btns"><a class="btn" href="%s" target="_blank" rel="noopener">Comment on YouTube ↗</a></div></section>'
            % (mini, esc(head[0]), esc(head[1]), esc(yt)))


HOME_CARD = ('<a class="ep" href="ep{nn}/" data-ep="{n}"><img src="img/ep{nn}.jpg" alt="Episode {n}: {t}"><div class="t">'
             '<small>Episode {n} · {k} words</small><h3>{t}</h3><span>Start practising →</span></div></a>')


def update_home(site, meta, n_words, thumb):
    """Thêm/cập nhật thẻ tập trên trang chủ, sắp theo số tập tăng dần."""
    home = os.path.join(site, "index.html")
    if not os.path.exists(home):
        shutil.copy(os.path.join(HERE, "home_template.html"), home)
    h = open(home, encoding="utf-8").read()
    card_re = re.compile(r'<a class="ep" href="ep(\d+)/".*?</a>', re.S)
    cards = {int(m.group(1)): m.group(0) for m in card_re.finditer(h)}
    nn = "%02d" % meta["ep"]
    cards[meta["ep"]] = HOME_CARD.format(nn=nn, n=meta["ep"], t=esc(meta["title"]), k=n_words)
    h = re.sub(r'\s*<a class="ep" href="ep\d+/".*?</a>', "", h, flags=re.S)
    h = re.sub(r"<!-- EPISODES.*?-->", "<!-- EPISODES -->\n    " + "\n    ".join(cards[k] for k in sorted(cards)), h, count=1)
    open(home, "w", encoding="utf-8").write(h)
    if thumb:
        os.makedirs(os.path.join(site, "img"), exist_ok=True)
        shutil.copy(thumb, os.path.join(site, "img", "ep%s.jpg" % nn))
    open(os.path.join(site, ".nojekyll"), "a").close()


def cmd_build(a):
    work = a.work
    meta = json.load(open(os.path.join(work, "meta.json")))
    W = json.load(open(os.path.join(work, "words.json")))
    cpath = os.path.join(work, "content.json")
    if not os.path.exists(cpath):
        sys.exit("NO_CONTENT: chưa có %s (Claude viết theo content_todo.json)." % cpath)
    C = json.load(open(cpath, encoding="utf-8"))
    miss = [v["word"] for v in W if v["word"] not in C]
    if miss:
        sys.exit("CONTENT_MISSING: content.json thiếu: " + ", ".join(miss))
    probs = []
    for v in W:
        c = C[v["word"]]
        if len(c.get("ex", [])) != 2:
            probs.append("%s: cần đúng 2 câu đời sống" % v["word"])
        for s in c.get("ex", []):
            if not re.search(r"\b" + word_re(c), s[0], re.I):
                probs.append("%s: câu '%s' không chứa từ" % (v["word"], s[0]))
    for v in W:
        c = C[v["word"]]
        if c.get("meaning"):
            v["meaning"] = c["meaning"]
        if v["source"] == "absent" and c.get("movie"):
            v["text"] = c["movie"]
        if not v["meaning"]:
            probs.append("%s: thiếu nghĩa tiếng Anh (thêm \"meaning\" vào content.json)" % v["word"])
        if v["source"] == "absent" and not v["text"]:
            probs.append("%s: từ không có trong lời thoại -> thêm \"movie\" (1 câu ví dụ) vào content.json" % v["word"])
    if probs:
        sys.exit("CONTENT_CHECK_FAIL:\n  " + "\n  ".join(probs))
    # giọng đọc
    tdir = os.path.join(work, "tts"); os.makedirs(tdir, exist_ok=True)
    if a.skip_tts:
        print("TTS: dùng lại file giọng đọc có sẵn trong %s" % tdir)
    tts = None if a.skip_tts else TTS()
    import aligner
    flat = lambda x: re.sub(r"[^a-z]", "", x.lower())

    def heard(p):
        return " ".join(w["w"] for w in aligner.asr_words(aligner.load(p), "en"))

    def say_checked(text, tries, out, exact):
        """Đọc rồi cho máy nghe lại; sai (thêm 'a', đọc méo...) thì đổi tốc độ/giọng. Trả về (ok, nghe được)."""
        last = ""
        for voice, speed in tries:
            tts.say(text, voice, out, speed)
            last = heard(out)
            if exact:
                if flat(last) == flat(text):
                    return True, last
            else:
                uk = lambda x: flat(x.replace("our", "or"))      # colour/color, savour/savor
                a, b = uk(text), uk(last)
                if difflib.SequenceMatcher(None, a, b).ratio() >= 0.9 and b[:3] == a[:3]:
                    return True, last
        return False, last

    # Giọng nam Michael cho phát âm từ đơn (chị duyệt 19/10/2026: giọng nữ Heart đọc từ đơn hay chèn tiếng "a" phía trước)
    WORD_TRIES = [("am_michael", 1.0), ("am_michael", 1.1), ("am_adam", 1.0), ("am_michael", 0.95),
                  ("af_heart", 1.0), ("af_nova", 1.0)]

    def word_from_carrier(base, out):
        """Cách cuối: đọc từ trong câu đệm 'Say X once more.', máy xác nhận nghe đúng X, rồi cắt riêng đoạn X."""
        tmp = out + ".carrier.mp3"
        for voice, carrier in [(v, c) for c in ("Say %s once more.", "Please %s it.", "I %s it now.", "It is %s now.")
                               for v in ("am_michael", "am_adam", "af_heart")]:
            tts.say(carrier % base, voice, tmp, 1.0)
            ws = aligner.asr_words(aligner.load(tmp), "en")
            n = len(base.split())
            for k in range(len(ws) - n):
                if flat(" ".join(w["w"] for w in ws[k:k + n])) == flat(base):
                    a, b = ws[k]["s"], min(ws[k + n]["s"], ws[k + n - 1]["e"] + 0.06)
                    for _ in range(6):            # cắt rồi nghe lại; còn dính chữ sau thì thu ngắn dần
                        subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-ss", "%.3f" % max(0, a - 0.03), "-to", "%.3f" % b, "-i", tmp,
                                        "-af", "afade=t=in:d=0.01,areverse,afade=t=in:d=0.04,areverse,adelay=120,apad=pad_dur=0.2",
                                        "-ac", "1", "-b:a", "48k", out], check=True)
                        got = [w["w"] for w in aligner.asr_words(aligner.load(out), "en")]
                        if len(got) <= n:
                            break
                        b -= 0.06
                    os.remove(tmp)
                    return True
        os.remove(tmp)
        return False
    issues = []
    for i, v in enumerate([] if a.skip_tts else W):
        c = C[v["word"]]
        w_txt = c["base"][:1].upper() + c["base"][1:] + "."
        ok, got = say_checked(w_txt, WORD_TRIES, os.path.join(tdir, "w%02d.mp3" % i), True)
        if not ok:
            if word_from_carrier(c["base"], os.path.join(tdir, "w%02d.mp3" % i)):
                print("  '%s': đọc riêng bị méo -> lấy từ câu đệm đã xác nhận đúng" % c["base"])
            else:
                issues.append("phát âm '%s' máy nghe ra '%s'" % (c["base"], got))
        for j, ex in enumerate(c["ex"]):
            v1 = "af_heart" if j == 0 else "am_puck"
            alt = "af_nova" if j == 0 else "am_michael"
            ok, got = say_checked(ex[0], [(v1, 0.95), (v1, 1.0), (alt, 1.0)], os.path.join(tdir, "e%02d_%d.mp3" % (i, j)), False)
            if not ok:
                issues.append("câu '%s' máy nghe ra '%s'" % (ex[0], got))
        if v["source"] != "episode" and v["text"]:
            v1 = "am_puck" if v["sp"] in MALE else "af_heart"
            ok, got = say_checked(v["text"], [(v1, 0.95), (v1, 1.0), ("am_michael" if v["sp"] in MALE else "af_nova", 1.0)],
                                  os.path.join(tdir, "m%02d.mp3" % i), False)
            if not ok:
                issues.append("câu phim '%s' máy nghe ra '%s'" % (v["text"], got))
    if issues:
        print("TTS_CHECK: %d chỗ cần nghe lại:\n  " % len(issues) + "\n  ".join(issues))
    else:
        print("TTS_CHECK: tất cả giọng đọc đã được máy nghe lại, đúng chữ.")
    print("TTS_OK", flush=True)

    def files_for(i, v):
        d = {"w%02d" % i: os.path.join(tdir, "w%02d.mp3" % i)}
        d["m%02d" % i] = os.path.join(work, v["clip"]) if v["source"] == "episode" else os.path.join(tdir, "m%02d.mp3" % i)
        for j in range(2):
            d["e%02d_%d" % (i, j)] = os.path.join(tdir, "e%02d_%d.mp3" % (i, j))
        return d
    b64 = lambda p: base64.b64encode(open(p, "rb").read()).decode()
    thumb = os.path.join(work, "thumb.jpg") if os.path.exists(os.path.join(work, "thumb.jpg")) else None
    desc = "Practise the %d new words from Fun English Tales Episode %d with the Thompson family's own voices, real-life examples and a quick quiz." % (len(W), meta["ep"])
    nn = "%02d" % meta["ep"]

    # (a) 1 file độc lập (gửi Zalo / Messenger)
    aud = {}
    for i, v in enumerate(W):
        for k, p in files_for(i, v).items():
            if os.path.exists(p):
                aud[k] = b64(p)
    page, nq = render(work, W, C, meta, aud, ("data:image/jpeg;base64," + b64(thumb)) if thumb else "")
    os.makedirs(os.path.join(work, "out"), exist_ok=True)
    single = os.path.join(work, "out", "FunEnglishTales_Tap%s_WordPractice.html" % nn)
    open(single, "w", encoding="utf-8").write(wrap(page, desc))
    open(os.path.join(work, "out", "artifact.html"), "w", encoding="utf-8").write(page)

    # (b) trang web (GitHub Pages): âm thanh gộp theo từng từ, tải khi cần
    if a.site:
        epdir = os.path.join(a.site, "ep" + nn)
        shutil.rmtree(epdir, ignore_errors=True)
        os.makedirs(os.path.join(epdir, "audio"))
        aud = {}
        for i, v in enumerate(W):
            pack = {}
            for k, p in files_for(i, v).items():
                if os.path.exists(p):
                    pack[k] = b64(p); aud[k] = "audio/w%02d.json" % i
            json.dump(pack, open(os.path.join(epdir, "audio", "w%02d.json" % i), "w"))
        tsrc = ""
        if thumb:
            os.makedirs(os.path.join(epdir, "img")); shutil.copy(thumb, os.path.join(epdir, "img", "thumb.jpg")); tsrc = "img/thumb.jpg"
        page, _ = render(work, W, C, meta, aud, tsrc)
        page = page.replace('<p class="foot">Fun English Tales', '<p class="foot"><a href="../" style="color:inherit;font-weight:800">← All episodes</a><br>Fun English Tales', 1)
        open(os.path.join(epdir, "index.html"), "w", encoding="utf-8").write(wrap(page, desc))
        update_home(a.site, meta, len(W), thumb)
        nfiles = sum(len(f) for _, _, f in os.walk(epdir))
        print("WEB_OK %s (%d file) · trang chủ đã cập nhật" % (epdir, nfiles))
    print("SINGLE_OK %s (%.1f MB) · %d từ · %d câu quiz" % (single, os.path.getsize(single) / 1e6, len(W), nq))


def cmd_extract(a):
    """File prompt 120 scene (.txt/.docx) -> file lời thoại dạng TRICH_VOICE (lấy phần [VO: ...] của mỗi scene)."""
    src = a.prompts
    if src.lower().endswith(".docx"):
        txt = subprocess.run(["pandoc", src, "-t", "plain", "--wrap=none"], capture_output=True, text=True, check=True).stdout
    else:
        txt = open(src, encoding="utf-8-sig").read()
    out, seen, miss = [], set(), []
    for line in txt.splitlines():
        m = re.match(r"^\s*Scene\s+(\d+[A-Za-z]?)\s*(?:\([^)]*\))?\s*:", line)
        if not m:
            continue
        n = m.group(1)
        if n in seen:
            continue                      # file prompt lặp dòng -> giữ lần đầu
        seen.add(n)
        i = line.find("[VO:")
        if i < 0:
            miss.append(n); out.append("Scene %s: " % n); continue
        s2, depth, j = line[i + 4:], 1, 0
        while j < len(s2) and depth:
            depth += {"[": 1, "]": -1}.get(s2[j], 0); j += 1
        vo = s2[:j - 1].strip()
        # thẻ nhân vật nằm giữa lời kể (vd "[ZOE_V1] texted: ...") -> tên nhân vật
        if not re.match(r"^\[[A-Z0-9_]+\]:", vo):
            vo = re.sub(r"\[([A-Z]+)\d*_V\d+\]", lambda mm: NAMES.get(mm.group(1), mm.group(1).title()), vo)
        out.append("Scene %s: %s" % (n, vo))
    open(a.out, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("EXTRACT_OK %s · %d scene%s" % (a.out, len(out), (" · KHÔNG CÓ VO: " + ", ".join(miss)) if miss else ""))


def cmd_test(a):
    """Kiểm tra nhanh trang web trên giả lập iPhone + Android (cần playwright + chromium)."""
    import http.server, threading, functools
    from playwright.sync_api import sync_playwright
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *x): pass
    h = functools.partial(Q, directory=a.site)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    ok = True
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        for dev in ["iPhone 13", "Pixel 7"]:
            ctx = b.new_context(**p.devices[dev]); pg = ctx.new_page()
            bad, errs = [], []
            pg.on("response", lambda r: bad.append(r.url) if r.status >= 400 and "fonts" not in r.url else None)
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto("http://127.0.0.1:%d/ep%02d/" % (port, a.ep)); pg.wait_for_timeout(1200)
            n = pg.evaluate("document.querySelectorAll('.card').length")
            pg.evaluate("document.querySelector('.card:last-of-type .movie .play').click()"); pg.wait_for_timeout(2000)
            lit = pg.evaluate("document.querySelectorAll('.card:last-of-type .tk.past,.card:last-of-type .tk.now').length+document.querySelectorAll('.card:last-of-type .play.on').length")
            hs = pg.evaluate("document.documentElement.scrollWidth>innerWidth")
            res = "PASS" if (n and lit and not errs and not bad and not hs) else "FAIL"
            ok &= res == "PASS"
            print("%s %-10s cards=%d audio=%s errors=%s 404=%s hscroll=%s" % (res, dev, n, bool(lit), errs, bad, hs))
            ctx.close()
        b.close()
    srv.shutdown()
    print("TEST=" + ("PASS" if ok else "FAIL"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--ep", required=True); p.add_argument("--title", required=True)
    p.add_argument("--mp3", required=True); p.add_argument("--script", required=True); p.add_argument("--vocab", required=True)
    p.add_argument("--yt", default=""); p.add_argument("--thumb"); p.add_argument("--question", default="")
    p.add_argument("--work", required=True)
    p = sub.add_parser("build"); p.add_argument("--work", required=True); p.add_argument("--site")
    p.add_argument("--skip-tts", action="store_true", help="dùng lại giọng đọc đã tạo (khi chỉ sửa giao diện hoặc thay vài file)")
    p = sub.add_parser("extract"); p.add_argument("--prompts", required=True); p.add_argument("--out", required=True)
    p = sub.add_parser("test"); p.add_argument("--site", required=True); p.add_argument("--ep", type=int, required=True)
    a = ap.parse_args()
    {"prepare": cmd_prepare, "build": cmd_build, "test": cmd_test, "extract": cmd_extract}[a.cmd](a)
