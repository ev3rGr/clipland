"""Animated word-by-word captions rendered as ASS subtitles (burned in by libass)."""
from .config import W, H


def _c(hex_rgb: str, alpha: int = 0) -> str:
    """'#RRGGBB' -> ASS '&HAABBGGRR'"""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


# name -> settings. "hl" = active word colour, "max_words" per caption chunk.
STYLES = {
    "bold": dict(label="Bold Pop", font="Montserrat Black", size=88, color="#FFFFFF", hl="#FFE11A",
                 outline=7, shadow=3, upper=True, max_words=3, max_chars=20, pop=True),
    "karaoke": dict(label="Karaoke", font="Montserrat ExtraBold", size=74, color="#FFFFFF", hl="#3CFF6B",
                    outline=6, shadow=2, upper=False, max_words=6, max_chars=30, pop=False),
    "single": dict(label="One Word", font="Anton", size=128, color="#FFFFFF", hl="#FFFFFF",
                   outline=8, shadow=4, upper=True, max_words=1, max_chars=40, pop=True),
    "neon": dict(label="Neon", font="Montserrat Black", size=84, color="#FFFFFF", hl="#FF3DCB",
                 outline=5, shadow=0, upper=True, max_words=3, max_chars=20, pop=True, glow="#00E5FF"),
    "minimal": dict(label="Minimal", font="Inter Bold", size=62, color="#FFFFFF", hl="#FFFFFF",
                    outline=3, shadow=2, upper=False, max_words=7, max_chars=36, pop=False),
}

POSITIONS = {"top": 0.22, "upper": 0.38, "middle": 0.5, "lower": 0.68, "bottom": 0.8}


def style_list():
    return [{"id": k, "label": v["label"], "color": v["color"], "hl": v["hl"], "font": v["font"]} for k, v in STYLES.items()]


def _esc(t: str) -> str:
    return t.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def chunk_words(words, max_words=3, max_chars=20, pause=0.55):
    chunks, cur = [], []
    for i, w in enumerate(words):
        if cur:
            gap = w["start"] - cur[-1]["end"]
            text_len = sum(len(x["word"]) + 1 for x in cur) + len(w["word"])
            ends_sentence = cur[-1]["word"][-1:] in ".!?"
            if len(cur) >= max_words or text_len > max_chars or gap > pause or ends_sentence:
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words, out_path, style="bold", position="lower", title=None, title_until=None,
              width=W, height=H, highlight=None, size_scale=1.0, title_margin=None, y_frac=None):
    st = dict(STYLES.get(style, STYLES["bold"]))
    if highlight:
        st["hl"] = highlight
    scale = (height / H) * float(size_scale)
    size = int(st["size"] * scale)
    y = int(height * (y_frac if y_frac is not None else POSITIONS.get(position, 0.68)))
    outline_col = _c(st.get("glow", "#000000"))
    blur = 6 if st.get("glow") else 0

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{st['font']},{size},{_c(st['color'])},{_c(st['hl'])},{outline_col},{_c('#000000', 0x60)},0,0,0,0,100,100,1,0,1,"
        f"{st['outline'] * scale:.1f},{st['shadow'] * scale:.1f},5,60,60,0,1",
        f"Style: Title,Montserrat ExtraBold,{int(62 * scale)},{_c('#111111')},{_c('#111111')},{_c('#FFFFFF')},{_c('#FFFFFF')},"
        f"0,0,0,0,100,100,0,0,3,{int(18 * scale)},0,8,90,90,{int(title_margin if title_margin is not None else height * 0.12)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    if title:
        t_end = title_until if title_until else (words[-1]["end"] + 1 if words else 5)
        lines.append(f"Dialogue: 2,{_ts(0)},{_ts(t_end)},Title,,0,0,0,,{{\\fad(150,200)}}{_esc(title)}")

    chunks = chunk_words(words, st["max_words"], st["max_chars"])
    pos = f"\\pos({width // 2},{y})"
    hl = _c(st["hl"])
    for ci, ch in enumerate(chunks):
        next_start = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else ch[-1]["end"] + 0.6
        ch_end = min(ch[-1]["end"] + 0.45, next_start)
        tokens = [_esc(w["word"].upper() if st["upper"] else w["word"]) for w in ch]
        for i, w in enumerate(ch):
            start = ch[0]["start"] if i == 0 else w["start"]
            end = ch[i + 1]["start"] if i + 1 < len(ch) else ch_end
            if end <= start:
                continue
            parts = []
            for j, tok in enumerate(tokens):
                if j == i and st["hl"] != st["color"]:
                    parts.append(f"{{\\c{hl}}}{tok}{{\\c{_c(st['color'])}}}")
                else:
                    parts.append(tok)
            anim = ""
            if st["pop"] and (i == 0 or st["max_words"] == 1):
                anim = "\\fscx80\\fscy80\\t(0,90,\\fscx108\\fscy108)\\t(90,160,\\fscx100\\fscy100)"
            glow = f"\\blur{blur}" if blur else ""
            lines.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{{{pos}{anim}{glow}}}{' '.join(parts)}")
            if blur:  # crisp text on top of the glow
                lines.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{{{pos}{anim}\\bord2\\3c&H000000&}}{' '.join(parts)}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out_path
