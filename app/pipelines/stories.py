"""Story videos (Reddit-style), fake text conversations and AI voiceovers."""
from .. import jobs, tts, captions, transcribe
from ..config import W, H, resolve_file
from ..media import run, probe, venc, AENC, MP4_FLAGS, ass_filter, audio_duration
from .common import background_input, music_input, out_path, output_entry, work_dir, write_srt
from .render_images import story_card, chat_layout, chat_frame


def _music_args(music, inputs_count):
    """Returns (input args, filter fragment producing [mus]) or ([], None)."""
    m = music_input(music)
    if not m:
        return [], None
    return ["-stream_loop", "-1", "-i", str(m)], f"[{inputs_count}:a]volume=0.12[mus]"


@jobs.handler("reddit")
def reddit_job(job, title, body, voice="en-US-AndrewMultilingualNeural", speed=1.1, background="gradient",
               music="none", style="bold", position="middle", community="r/AskReddit", username="throwaway",
               card_theme="light", highlight=None, read_title=True):
    wd = work_dir(job)
    job.update(0.05, "Generating voiceover")
    title_dur = 0.0
    if read_title and title.strip():
        tmp3 = wd / "title.mp3"
        tts.synthesize(title, voice, tmp3, speed)
        title_dur = audio_duration(tmp3) + 0.3
    job.update(0.2, "Narrating story")
    body_mp3 = wd / "body.mp3"
    words = tts.synthesize(body, voice, body_mp3, speed)
    body_dur = audio_duration(body_mp3)
    total = title_dur + body_dur + 0.6
    shift = [{**w, "start": w["start"] + title_dur, "end": w["end"] + title_dur} for w in words]
    card_until = title_dur

    job.update(0.3, "Designing post card")
    card = wd / "card.png"
    story_card(title, community, username, card_theme).save(card)
    ass = wd / "subs.ass"
    captions.build_ass([w for w in shift if w["start"] >= card_until - 0.05], ass, style, position, highlight=highlight)

    bg_args, bg_chain = background_input(background, total)
    inputs = [*bg_args]
    idx = 1
    voice_parts = []
    if title_dur:
        inputs += ["-i", wd / "title.mp3"]; voice_parts.append(idx); idx += 1
    inputs += ["-i", body_mp3]; voice_parts.append(idx); idx += 1
    inputs += ["-loop", "1", "-i", card]; card_idx = idx; idx += 1
    mus_args, mus_chain = _music_args(music, idx)
    inputs += mus_args

    if card_until:
        fc = [f"[0:v]{bg_chain}[bg]",
              f"[{card_idx}:v]format=rgba,fade=t=in:st=0:d=0.15:alpha=1,"
              f"fade=t=out:st={max(0.1, card_until - 0.2):.2f}:d=0.2:alpha=1[card]",
              f"[bg][card]overlay=(W-w)/2:(H-h)/2:enable='lt(t,{card_until:.2f})'[v1]",
              f"[v1]{ass_filter(ass)}[v]"]
    else:
        fc = [f"[0:v]{bg_chain},{ass_filter(ass)}[v]", f"[{card_idx}:v]nullsink"]
    if len(voice_parts) == 2:
        fc.append(f"[{voice_parts[0]}:a]apad=pad_dur=0.3[ta];[ta][{voice_parts[1]}:a]concat=n=2:v=0:a=1[voice]")
    else:
        fc.append(f"[{voice_parts[0]}:a]anull[voice]")
    if mus_chain:
        fc += [mus_chain, "[voice][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"]
    else:
        fc.append("[voice]anull[a]")
    out = out_path(job, "story")
    run(["ffmpeg", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
         *venc(), "-r", "30", *AENC, *MP4_FLAGS, out], job, total, 0.35, 1.0, "Rendering story")
    srt = out.with_suffix(".srt")
    write_srt(shift, srt)
    return {"outputs": [output_entry(out, title[:60] or "Story video", srt=f"outputs/{srt.name}")]}


@jobs.handler("faketext")
def faketext_job(job, messages, contact="Alex", voice_me="en-US-AndrewMultilingualNeural",
                 voice_them="en-US-AvaMultilingualNeural", theme="light", background="gradient", music="none", speed=1.1):
    msgs = [{"from": m.get("from", "them"), "text": tts.clean_text(str(m.get("text", "")))} for m in messages]
    msgs = [m for m in msgs if m["text"]]
    if not msgs:
        raise ValueError("Add at least one message")
    wd = work_dir(job)
    # pop sound
    pop = wd / "pop.wav"
    run(["ffmpeg", "-f", "lavfi", "-i", "aevalsrc='0.35*sin(2*PI*(700+2500*t)*t)*exp(-38*t)':s=48000:d=0.14",
         "-ac", "2", pop])
    segs, durs = [], []
    for i, m in enumerate(msgs):
        job.update(0.05 + 0.45 * i / len(msgs), f"Voicing message {i + 1}/{len(msgs)}")
        mp3 = wd / f"m{i}.mp3"
        tts.synthesize(m["text"], voice_me if m["from"] == "me" else voice_them, mp3, speed)
        seg = wd / f"seg{i}.wav"
        run(["ffmpeg", "-i", pop, "-i", mp3, "-filter_complex",
             "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[p];[1:a]aformat=sample_rates=48000:channel_layouts=stereo,"
             "adelay=120|120,apad=pad_dur=0.35[v];[p][v]amix=inputs=2:duration=longest:normalize=0[a]",
             "-map", "[a]", seg])
        segs.append(seg)
        durs.append(audio_duration(seg))

    job.update(0.55, "Drawing chat screens")
    layout, content_h = chat_layout(msgs, theme=theme)
    panel_h = int(min(1150, max(620, 190 + content_h + 70)))
    lines = []
    for i in range(len(msgs)):
        png = wd / f"f{i}.png"
        chat_frame(msgs, layout, i, contact, theme, height=panel_h).save(png)
        lines += [f"file '{png}'", f"duration {durs[i]:.3f}"]
    lines.append(f"file '{wd / f'f{len(msgs) - 1}.png'}'")
    (wd / "frames.txt").write_text("\n".join(lines))
    (wd / "audio.txt").write_text("\n".join(f"file '{s}'" for s in segs))
    voice = wd / "voice.wav"
    run(["ffmpeg", "-f", "concat", "-safe", "0", "-i", wd / "audio.txt", "-c", "copy", voice])
    total = sum(durs) + 0.8

    bg_args, bg_chain = background_input(background, total)
    inputs = [*bg_args, "-f", "concat", "-safe", "0", "-i", wd / "frames.txt", "-i", voice]
    mus_args, mus_chain = _music_args(music, 3)
    inputs += mus_args
    fc = [f"[0:v]{bg_chain}[bg]", "[1:v]format=rgba,fps=30[chat]",
          "[bg][chat]overlay=(W-w)/2:110:eof_action=repeat[v]"]
    if mus_chain:
        fc += [mus_chain, "[2:a][mus]amix=inputs=2:duration=first:normalize=0[a]"]
    else:
        fc.append("[2:a]anull[a]")
    out = out_path(job, "texts")
    run(["ffmpeg", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
         *venc(), "-r", "30", *AENC, *MP4_FLAGS, out], job, total, 0.6, 1.0, "Rendering conversation")
    return {"outputs": [output_entry(out, f"Texts with {contact}")]}


@jobs.handler("voiceover")
def voiceover_job(job, script, voice="en-US-AndrewMultilingualNeural", speed=1.0, video=None, background="gradient",
                  audio_mode="replace", style="bold", position="lower", music="none", highlight=None, layout="vertical"):
    """Narrate a script over a video (your upload or a background)."""
    wd = work_dir(job)
    job.update(0.05, "Generating voiceover")
    mp3 = wd / "vo.mp3"
    words = tts.synthesize(script, voice, mp3, speed)
    dur = audio_duration(mp3) + 0.5
    if video:
        src = resolve_file(video)
        info = probe(src)
        loop = ["-stream_loop", "-1"] if info["duration"] < dur else []
        v_in = [*loop, "-i", src]
        if layout == "vertical":
            from ..reframe import vertical_filter
            chain, ow, oh = vertical_filter("fit" if info["width"] > info["height"] else "center", info["width"], info["height"]), W, H
        else:
            ow, oh = info["width"] - info["width"] % 2, info["height"] - info["height"] % 2
            chain = f"scale={ow}:{oh},setsar=1"
        has_src_audio = info["has_audio"]
    else:
        v_in, chain = background_input(background, dur)
        ow, oh, has_src_audio = W, H, False
    ass = wd / "subs.ass"
    fc = [f"[0:v]{chain}[base]"]
    if style != "none":
        captions.build_ass(words, ass, style, position, width=ow, height=oh, highlight=highlight)
        fc.append(f"[base]{ass_filter(ass)}[v]")
    else:
        fc.append("[base]null[v]")
    inputs = [*v_in, "-i", mp3]
    mus_args, mus_chain = _music_args(music, 2)
    inputs += mus_args
    mix = ["[1:a]apad[vo]"]
    labels = ["[vo]"]
    if has_src_audio and audio_mode == "mix":
        mix.append("[0:a]volume=0.18[orig]"); labels.append("[orig]")
    if mus_chain:
        mix.append(mus_chain); labels.append("[mus]")
    if len(labels) > 1:
        mix.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0[a]")
    else:
        mix.append("[vo]anull[a]")
    out = out_path(job, "voiceover")
    run(["ffmpeg", *inputs, "-filter_complex", ";".join(fc + mix), "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
         *venc(), "-r", "30", *AENC, *MP4_FLAGS, out], job, dur, 0.2, 1.0, "Rendering")
    srt = out.with_suffix(".srt")
    write_srt(words, srt)
    return {"outputs": [output_entry(out, "Voiceover video", srt=f"outputs/{srt.name}")]}


@jobs.handler("tts")
def tts_job(job, text, voice="en-US-AndrewMultilingualNeural", speed=1.0, pitch=0):
    out = out_path(job, "voice", "mp3")
    job.update(0.2, "Generating speech")
    tts.synthesize(text, voice, out, speed, pitch)
    return {"outputs": [output_entry(out, "Voiceover audio")]}
