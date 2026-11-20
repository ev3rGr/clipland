"""PIL renderers: story post card and chat (text message) screens. Original designs."""
import hashlib
import random

from PIL import Image, ImageDraw, ImageFont

from ..config import FONTS

_font_cache = {}


def font(name, size):
    key = (name, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(FONTS / f"{name}.ttf"), size)
    return _font_cache[key]


def wrap(draw, text, fnt, max_w):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            test = f"{cur} {word}".strip()
            if draw.textlength(test, font=fnt) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                # hard-break very long words
                while draw.textlength(word, font=fnt) > max_w:
                    cut = len(word)
                    while cut > 1 and draw.textlength(word[:cut], font=fnt) > max_w:
                        cut -= 1
                    lines.append(word[:cut]); word = word[cut:]
                cur = word
        lines.append(cur)
    return lines


def _avatar_color(seed):
    h = int(hashlib.md5(seed.encode()).hexdigest()[:6], 16)
    palette = ["#FF6B35", "#7B61FF", "#00B386", "#FF3D7F", "#1E88E5", "#F4B400", "#00ACC1"]
    return palette[h % len(palette)]


def story_card(title, community="r/AskReddit", username="anonymous", theme="light", width=920, upvotes=None, comments=None):
    dark = theme == "dark"
    bg, fg, sub = ("#1A1A1B", "#F2F2F2", "#9A9A9A") if dark else ("#FFFFFF", "#111111", "#7A7A7A")
    pad = 44
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    tf = font("Inter-Bold", 50)
    lines = wrap(tmp, title, tf, width - 2 * pad)
    line_h = 64
    h = pad + 96 + 26 + len(lines) * line_h + 30 + 60 + pad
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, width - 1, h - 1), radius=40, fill=bg)
    # header
    ac = _avatar_color(community)
    d.ellipse((pad, pad, pad + 96, pad + 96), fill=ac)
    initial = (community.replace("r/", "")[:1] or "R").upper()
    f_init = font("Montserrat-Black", 52)
    d.text((pad + 48, pad + 50), initial, font=f_init, fill="white", anchor="mm")
    d.text((pad + 120, pad + 10), community, font=font("Inter-Bold", 36), fill=fg)
    d.text((pad + 120, pad + 56), f"u/{username} · {random.randint(2, 23)}h", font=font("Inter-Medium", 30), fill=sub)
    # verified-ish badge (generic check)
    bx = pad + 120 + d.textlength(community, font=font("Inter-Bold", 36)) + 14
    d.ellipse((bx, pad + 16, bx + 32, pad + 48), fill="#2F80ED")
    d.line((bx + 8, pad + 32, bx + 14, pad + 39, bx + 25, pad + 24), fill="white", width=4)
    # title
    y = pad + 96 + 26
    for ln in lines:
        d.text((pad, y), ln, font=tf, fill=fg)
        y += line_h
    # footer: up arrow, count, bubble, count, share
    y += 30
    fsm = font("Inter-Bold", 32)
    up = upvotes or f"{random.randint(2, 98)}.{random.randint(1, 9)}k"
    cm = comments or f"{random.randint(1, 9)}.{random.randint(1, 9)}k"
    x = pad
    d.polygon([(x + 22, y + 4), (x + 42, y + 28), (x + 30, y + 28), (x + 30, y + 46), (x + 14, y + 46), (x + 14, y + 28), (x + 2, y + 28)], fill="#FF4500")
    d.text((x + 56, y + 6), up, font=fsm, fill=sub)
    x += 56 + d.textlength(up, font=fsm) + 50
    d.rounded_rectangle((x, y + 6, x + 42, y + 38), radius=12, outline=sub, width=4)
    d.polygon([(x + 10, y + 36), (x + 10, y + 48), (x + 22, y + 36)], fill=sub)
    d.text((x + 56, y + 6), cm, font=fsm, fill=sub)
    x += 56 + d.textlength(cm, font=fsm) + 50
    d.line((x, y + 26, x + 34, y + 26), fill=sub, width=4)
    d.line((x + 20, y + 12, x + 34, y + 26, x + 20, y + 40), fill=sub, width=4)
    d.text((x + 50, y + 6), "Share", font=fsm, fill=sub)
    return img


# ---------- chat screens ----------

def _chat_theme(theme):
    if theme == "dark":
        return dict(bg="#000000", header="#1C1C1E", name="#FFFFFF", sub="#8E8E93", me="#0A84FF", me_text="#FFFFFF",
                    them="#262628", them_text="#FFFFFF", divider="#2C2C2E")
    return dict(bg="#FFFFFF", header="#F6F6F6", name="#000000", sub="#8E8E93", me="#0A84FF", me_text="#FFFFFF",
                them="#E9E9EB", them_text="#000000", divider="#DADADA")


def chat_layout(messages, width=960, theme="light"):
    """Pre-compute bubble geometry for all messages."""
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f = font("Inter-Regular", 42)
    max_bw = int(width * 0.68)
    pad_x, pad_y, line_h, gap = 34, 22, 54, 14
    out, y = [], 30
    prev = None
    for m in messages:
        lines = wrap(tmp, m["text"], f, max_bw - 2 * pad_x)
        tw = max(tmp.textlength(ln, font=f) for ln in lines) if lines else 0
        bw = int(tw + 2 * pad_x)
        bh = len(lines) * line_h + 2 * pad_y - 8
        if prev is not None and prev != m["from"]:
            y += 22
        out.append({"lines": lines, "w": bw, "h": bh, "y": y, "from": m["from"]})
        y += bh + gap
        prev = m["from"]
    return out, y


def chat_frame(messages, layout, upto, contact="Mom", theme="light", width=960, height=1080):
    t = _chat_theme(theme)
    f = font("Inter-Regular", 42)
    header_h = 190
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=48, fill=255)
    body = Image.new("RGBA", (width, height), t["bg"])
    d = ImageDraw.Draw(body)

    # messages (scrolled so the newest is visible)
    view_h = height - header_h - 30
    shown = layout[: upto + 1]
    bottom = shown[-1]["y"] + shown[-1]["h"] if shown else 0
    scroll = max(0, bottom - view_h + 20)
    for i, b in enumerate(shown):
        y = header_h + b["y"] - scroll
        if y + b["h"] < header_h:
            continue
        me = b["from"] == "me"
        x = width - 30 - b["w"] if me else 30
        col = t["me"] if me else t["them"]
        d.rounded_rectangle((x, y, x + b["w"], y + b["h"]), radius=40, fill=col)
        last_of_run = i == len(layout) - 1 or layout[i + 1]["from"] != b["from"] or i == upto
        if last_of_run:  # little tail
            if me:
                d.polygon([(x + b["w"] - 30, y + b["h"] - 30), (x + b["w"] + 12, y + b["h"]), (x + b["w"] - 46, y + b["h"])], fill=col)
            else:
                d.polygon([(x + 30, y + b["h"] - 30), (x - 12, y + b["h"]), (x + 46, y + b["h"])], fill=col)
        ty = y + 20
        for ln in b["lines"]:
            d.text((x + 34, ty), ln, font=f, fill=t["me_text"] if me else t["them_text"])
            ty += 54
    if upto == len(layout) - 1 and layout and layout[-1]["from"] == "me":
        last = layout[-1]
        d.text((width - 36, header_h + last["y"] - scroll + last["h"] + 6), "Read", font=font("Inter-Medium", 26),
               fill=t["sub"], anchor="ra")

    # header on top
    d.rectangle((0, 0, width, header_h), fill=t["header"])
    d.line((0, header_h, width, header_h), fill=t["divider"], width=2)
    d.line((52, 62, 30, 84, 52, 106), fill=t["me"], width=6)
    ac = _avatar_color(contact)
    cx = width // 2
    d.ellipse((cx - 50, 18, cx + 50, 118), fill=ac)
    d.text((cx, 69), (contact[:1] or "?").upper(), font=font("Inter-Bold", 50), fill="white", anchor="mm")
    d.text((cx, 150), contact, font=font("Inter-Medium", 34), fill=t["name"], anchor="mm")
    img.paste(body, (0, 0), mask)
    return img
