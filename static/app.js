/* Clipland — vanilla JS single-page app (no build step). */
"use strict";

// ---------- tiny helpers ----------
const $ = (s, el = document) => el.querySelector(s);
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat(Infinity)) if (k != null && k !== false) el.append(k.nodeType ? k : document.createTextNode(String(k)));
  return el;
}
const api = {
  async req(method, url, body) {
    const r = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`);
    return data;
  },
  get: (u) => api.req("GET", u), post: (u, b) => api.req("POST", u, b || {}), del: (u) => api.req("DELETE", u),
};
function toast(msg, err = false) {
  const t = h("div", { class: "toast" + (err ? " err" : "") }, msg);
  $("#toast").append(t); setTimeout(() => t.remove(), err ? 6000 : 3000);
}
const fmtTime = (s) => { s = Math.max(0, +s || 0); const m = Math.floor(s / 60); return `${m}:${(s % 60).toFixed(1).padStart(4, "0")}`; };
const fmtSize = (b) => b > 1e9 ? (b / 1e9).toFixed(1) + " GB" : b > 1e6 ? (b / 1e6).toFixed(1) + " MB" : Math.ceil(b / 1e3) + " KB";
const media = (ref) => ref ? `/media/${ref}` : "";
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem("cl_" + k)) ?? d; } catch { return d; } },
                set(k, v) { try { localStorage.setItem("cl_" + k, JSON.stringify(v)); } catch {} } };

const ICON = {
  home: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  autoclip: '<path d="M4 7h16M4 12h10M4 17h7"/><path d="M17 14l4 3-4 3z"/>',
  story: '<path d="M5 4h14v12H9l-4 4z"/><path d="M9 9h6M9 12h4"/>',
  texts: '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M9 7h6M9 11h4"/>',
  voiceover: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  captions: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 13h4M13 13h4M7 16h7"/>',
  tools: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
  library: '<path d="M4 5h6l2 2h8v12H4z"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  calc: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 12h2M12 12h2M8 16h2M12 16h4"/>',
};
const icon = (n) => `<svg viewBox="0 0 24 24">${ICON[n] || ""}</svg>`;

const ROUTES = [
  { id: "home", label: "Home" },
  { sec: "Create" },
  { id: "autoclip", label: "AutoClip", desc: "Podcasts, gameplay, streams or trailers into viral vertical clips.", color: "#C6FF3D" },
  { id: "story", label: "Story Videos", desc: "Narrated Reddit-style stories over gameplay.", color: "#FF8A3D" },
  { id: "texts", label: "Fake Texts", desc: "Animated text conversations with voices.", color: "#3DA2FF" },
  { id: "voiceover", label: "AI Voiceover", desc: "Narrate any script over your video or a background.", color: "#B78CFF" },
  { id: "captions", label: "Auto Captions", desc: "Burn animated word-by-word subtitles into any video.", color: "#FF5FA2" },
  { sec: "Utilities" },
  { id: "tools", label: "Free Tools", desc: "Trim, compress, GIF, speed, merge, enhance audio…", color: "#3DDC97" },
  { id: "library", label: "Library" },
  { id: "calc", label: "Calculators" },
  { id: "settings", label: "AI Settings" },
];

// ---------- global state ----------
const S = { options: null, status: null, files: {} };
async function loadFiles(kind, force = false) {
  if (!force && S.files[kind]) return S.files[kind];
  S.files[kind] = await api.get(`/api/files?kind=${kind}`);
  return S.files[kind];
}

// ---------- reusable widgets ----------
function seg(options, value, onChange) {
  const el = h("div", { class: "seg" });
  const w = { el, value };
  const render = () => {
    el.replaceChildren(...options.map(([v, label]) => h("button", { type: "button", class: w.value === v ? "on" : "",
      onclick: () => { w.value = v; render(); onChange && onChange(v); } }, label)));
  };
  render();
  return w;
}

function field(label, control, hint) {
  return h("div", { class: "field" }, h("label", {}, label), control.el || control, hint ? h("div", { class: "hint", style: { marginTop: "0" } }, hint) : null);
}

function styleTiles(value = "bold") {
  const w = { value, el: h("div", { class: "styles" }) };
  const render = () => w.el.replaceChildren(...S.options.caption_styles.concat([{ id: "none", label: "No captions", color: "#888", hl: "#888", font: "Inter" }]).map((s) =>
    h("div", { class: "style-tile" + (w.value === s.id ? " on" : ""), onclick: () => { w.value = s.id; render(); } },
      h("span", { style: { fontFamily: `"${s.font}", Inter`, color: s.color } },
        s.id === "none" ? "—" : s.id === "single" ? "WOW" : [h("span", { style: { color: s.hl, fontFamily: "inherit" } }, s.id === "minimal" ? "Hello" : "HEY"), " YOU"]),
      h("small", {}, s.label))));
  render();
  return w;
}

function voiceSelect(value) {
  const sel = h("select", {}, S.options.voices.map((v) => h("option", { value: v.id, selected: v.id === value }, v.label)));
  const more = h("option", { value: "__more" }, "More voices (all languages)…");
  sel.append(more);
  sel.addEventListener("change", async () => {
    if (sel.value !== "__more") return;
    sel.disabled = true;
    try {
      const all = await api.get("/api/voices");
      more.remove();
      const g = h("optgroup", { label: "All voices" }, all.map((v) => h("option", { value: v.id }, `${v.id} (${v.gender})`)));
      sel.append(g);
      sel.value = S.options.voices[0].id;
    } catch (e) { toast("Couldn't load voices: " + e.message, true); }
    sel.disabled = false;
  });
  let audio;
  const btn = h("button", { type: "button", class: "sm", title: "Preview voice", onclick: async () => {
    btn.disabled = true; btn.innerHTML = '<span class="spin"></span>';
    try {
      const { url } = await api.post("/api/tts/preview", { voice: sel.value });
      audio?.pause(); audio = new Audio(url); audio.play();
    } catch (e) { toast(e.message, true); }
    btn.disabled = false; btn.textContent = "▶ Preview";
  } }, "▶ Preview");
  const el = h("div", { class: "btns", style: { flexWrap: "nowrap" } }, sel, btn);
  return { el, get value() { return sel.value; } };
}

function libSelect(kind, opts = {}) {
  const sel = h("select", {});
  const w = { el: h("div", { class: "btns", style: { flexWrap: "nowrap" } }, sel), get value() { return sel.value; } };
  const fill = async (selectRef) => {
    const files = await loadFiles(kind, true);
    sel.replaceChildren(...(opts.extra || []).map(([v, l]) => h("option", { value: v }, l)),
      ...files.map((f) => h("option", { value: f.ref, selected: f.ref === selectRef }, f.name)));
  };
  const up = h("input", { type: "file", accept: opts.accept || "video/*", hidden: true, onchange: async () => {
    if (!up.files[0]) return;
    upBtn.disabled = true;
    try {
      const f = await uploadFile(up.files[0], kind, (p) => (upBtn.textContent = `${Math.round(p * 100)}%`));
      await fill(f.ref); toast("Uploaded " + f.name);
    } catch (e) { toast(e.message, true); }
    upBtn.disabled = false; upBtn.textContent = "Upload"; up.value = "";
  } });
  const upBtn = h("button", { type: "button", class: "sm", onclick: () => up.click() }, "Upload");
  w.el.append(upBtn, up);
  fill(opts.value);
  return w;
}

function uploadFile(file, kind, onProgress) {
  return new Promise((resolve, reject) => {
    const fd = new FormData(); fd.append("file", file); fd.append("kind", kind);
    const x = new XMLHttpRequest();
    x.open("POST", "/api/upload");
    x.upload.onprogress = (e) => e.lengthComputable && onProgress && onProgress(e.loaded / e.total);
    x.onload = () => { let d = {}; try { d = JSON.parse(x.responseText); } catch {}
      x.status < 300 ? (delete S.files[kind], resolve(d)) : reject(new Error(d.detail || "Upload failed")); };
    x.onerror = () => reject(new Error("Upload failed"));
    x.send(fd);
  });
}

/** Big drag-and-drop video picker with library dropdown. */
// ---------- paste a link: detect the site, preview, download ----------
function linkImporter(kind, onImported) {
  const input = h("input", { type: "url", placeholder: kind === "music" ? "…or paste a link (YouTube, SoundCloud, TikTok…)" : "…or paste a link: YouTube, Twitch, Kick, TikTok, X, Instagram, Drive, direct .mp4…" });
  const badge = h("span", { class: "src-badge", style: { display: "none" } });
  const card = h("div", { class: "link-card", style: { display: "none" } });
  const AUTO_MAX = 2 * 3600;  // auto-download anything up to 2h; longer VODs wait for a click (pick a part first)
  let seq = 0, timer = null, jobId = null;
  const hms = (x) => { x = Math.round(x || 0); const hh = Math.floor(x / 3600), mm = Math.floor(x % 3600 / 60), ss = x % 60; return (hh ? hh + ":" + String(mm).padStart(2, "0") : mm) + ":" + String(ss).padStart(2, "0"); };
  const reset = () => { badge.style.display = "none"; card.style.display = "none"; card.replaceChildren(); };

  async function inspect() {
    const url = input.value.trim();
    const my = ++seq;
    if (!url) return reset();
    let d;
    try { d = await api.get(`/api/url/detect?url=${encodeURIComponent(url)}`); } catch { return; }
    if (my !== seq) return;
    if (!d.ok) { badge.style.display = ""; badge.className = "src-badge bad"; badge.textContent = "Not a link"; card.style.display = "none"; return; }
    badge.style.display = ""; badge.className = "src-badge"; badge.textContent = `${d.icon} ${d.label}${d.kind !== "video" ? " · " + d.kind : ""}`;
    card.style.display = ""; card.replaceChildren(h("div", { class: "muted small" }, h("span", { class: "spin" }), ` Reading ${d.label} link…`));
    if (d.kind === "live") return card.replaceChildren(h("p", { class: "err small" }, `That's a live channel page. Paste a VOD (e.g. twitch.tv/videos/…) or a clip link instead.`));
    if (d.kind === "playlist") return card.replaceChildren(h("p", { class: "err small" }, "That's a playlist. Open one video and paste its link."));
    let info;
    try { info = await api.get(`/api/url/info?url=${encodeURIComponent(url)}`); } catch (e) { if (my === seq) card.replaceChildren(h("p", { class: "err small" }, e.message)); return; }
    if (my !== seq) return;
    drawCard(info, true);
  }

  function drawCard(info, auto) {
    const quals = [["2160", "4K"], ["1440", "1440p"], ["1080", "1080p"], ["720", "720p"], ["480", "480p"]].filter(([q]) => !info.max_height || +q <= Math.max(480, info.max_height));
    let quality = store.get("dl_quality", "1080");
    if (!quals.some(([q]) => q === quality)) quality = quals[0]?.[0] || "1080";
    const qSel = h("select", { style: { width: "auto" }, onchange: (e) => { quality = e.target.value; store.set("dl_quality", quality); } },
      quals.map(([q, l]) => h("option", { value: q, selected: q === quality }, l)));
    const long = info.duration && info.duration > AUTO_MAX;
    const partChk = h("input", { type: "checkbox", checked: !!long, onchange: () => (partRow.style.display = partChk.checked ? "" : "none") });
    const st = h("input", { type: "text", value: "0:00", style: { width: "90px" } });
    const en = h("input", { type: "text", value: info.duration ? hms(Math.min(info.duration, long ? 3600 : info.duration)) : "", placeholder: "end", style: { width: "90px" } });
    const partRow = h("div", { class: "btns", style: { display: long ? "" : "none", alignItems: "center" } }, h("span", { class: "muted small" }, "From"), st, h("span", { class: "muted small" }, "to"), en);
    const status = h("div", { class: "muted small" });
    const bar = h("i"); const prog = h("div", { class: "progress", style: { display: "none" } }, bar);
    const dl = h("button", { class: "primary sm", onclick: () => start() }, "⬇ Download");
    const cancel = h("button", { class: "sm", style: { display: "none" }, onclick: async () => { if (jobId) await api.post(`/api/jobs/${jobId}/cancel`).catch(() => {}); } }, "Cancel");
    const useBtn = info.already ? h("button", { class: "violet sm", onclick: () => onImported(info.already) }, "Use the copy in your library") : null;
    const meta = [info.uploader, info.duration ? hms(info.duration) : null, info.max_height ? `up to ${info.max_height}p` : null].filter(Boolean).join(" · ");
    card.replaceChildren(...[
      h("div", { class: "link-head" },
        info.thumbnail ? h("img", { src: info.thumbnail, alt: "", referrerpolicy: "no-referrer" }) : h("div", { class: "ph" }, info.icon),
        h("div", { style: { minWidth: 0, flex: 1 } },
          h("div", { class: "name" }, info.title || input.value.trim()), h("div", { class: "muted small" }, `${info.icon} ${info.label}` + (meta ? " · " + meta : "")),
          info.warning ? h("div", { class: "muted small" }, info.warning) : null,
          info.is_live ? h("div", { class: "err small" }, "This is live right now. Only the part streamed so far can be downloaded; a finished VOD works better.") : null)),
      kind === "music" ? null : h("div", { class: "btns", style: { alignItems: "center" } }, h("span", { class: "muted small" }, "Quality"), qSel,
        h("label", { class: "check", style: { margin: 0 } }, partChk, "Only download a part")),
      partRow,
      long ? h("div", { class: "hint", style: { margin: 0 } }, `Long video (${hms(info.duration)}). Pick the part you want, or untick to download all of it.`) : null,
      h("div", { class: "btns" }, dl, useBtn, cancel), prog, status].filter(Boolean));

    async function start() {
      const params = { url: info.url || input.value.trim(), kind, quality };
      if (partChk.checked) { params.start = st.value.trim() || null; params.end = en.value.trim() || null; }
      dl.disabled = true; cancel.style.display = ""; prog.style.display = ""; bar.style.width = "2%"; status.textContent = "Starting…";
      let job;
      try { job = await api.post("/api/jobs/import_url", { params }); } catch (e) { status.textContent = e.message; dl.disabled = false; return; }
      jobId = job.id; trackJob(job, {});
      while (true) {
        await new Promise((r) => setTimeout(r, 800));
        try { job = await api.get(`/api/jobs/${jobId}`); } catch { continue; }
        bar.style.width = Math.max(2, job.progress * 100) + "%";
        status.textContent = job.message || "";
        if (job.status === "done") {
          status.textContent = job.result.reused ? "Already downloaded. Using your copy." : "✓ Downloaded";
          cancel.style.display = "none"; prog.style.display = "none";
          onImported(job.result.file); input.value = ""; setTimeout(reset, 2500); break;
        }
        if (["error", "cancelled"].includes(job.status)) {
          status.className = "err small"; status.textContent = job.status === "cancelled" ? "Cancelled" : job.error.replace(/^\w+Error: /, "");
          cancel.style.display = "none"; prog.style.display = "none"; dl.disabled = false; break;
        }
      }
      jobId = null;
    }
    if (auto && info.already) { status.textContent = "✓ Already in your library. Selected it."; onImported(info.already); }
    else if (auto && !long && !info.is_live) start();
  }

  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(inspect, 450); });
  input.addEventListener("paste", () => { clearTimeout(timer); timer = setTimeout(inspect, 30); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(timer); inspect(); } });
  const el = h("div", { class: "link-import" }, h("div", { class: "link-row" }, input, badge), card);
  return { el, setUrl: (u) => { input.value = u; inspect(); } };
}

function videoPicker(onChange, kind = "uploads") {
  const thumb = h("div", { class: "thumb" });
  const name = h("div", { class: "name" }, "No video selected");
  const sub = h("div", { class: "muted small" }, "Drop a video here, upload, or pick from your library");
  const bar = h("i");
  const prog = h("div", { class: "progress", style: { display: "none" } }, bar);
  const sel = h("select", { style: { maxWidth: "220px" } });
  const input = h("input", { type: "file", accept: "video/*,audio/*", hidden: true });
  const w = { value: null, info: null };
  const choose = (f) => {
    w.value = f?.ref || null; w.info = f || null;
    name.textContent = f ? f.name : "No video selected";
    sub.textContent = f ? [f.duration ? fmtTime(f.duration) : "", f.width ? `${f.width}×${f.height}` : "", f.size ? fmtSize(f.size) : ""].filter(Boolean).join(" · ") : "Drop a video here, upload, or pick from your library";
    thumb.style.backgroundImage = f?.thumb ? `url(${f.thumb})` : "";
    sel.value = w.value || "";
    onChange && onChange(f);
  };
  const fill = async () => {
    const files = await loadFiles(kind, true);
    sel.replaceChildren(h("option", { value: "" }, "Choose from library…"), ...files.map((f) => h("option", { value: f.ref }, f.name)));
    if (w.value) sel.value = w.value;
  };
  sel.onchange = async () => {
    const f = S.files[kind].find((x) => x.ref === sel.value);
    if (!f) return choose(null);
    try { Object.assign(f, await api.get(`/api/probe?ref=${encodeURIComponent(f.ref)}`)); } catch {}
    choose(f);
  };
  const doUpload = async (file) => {
    prog.style.display = ""; bar.style.width = "0";
    try {
      const f = await uploadFile(file, kind, (p) => { bar.style.width = p * 100 + "%"; sub.textContent = `Uploading ${Math.round(p * 100)}%`; });
      await fill(); choose(f);
    } catch (e) { toast(e.message, true); sub.textContent = "Upload failed"; }
    prog.style.display = "none";
  };
  input.onchange = () => input.files[0] && doUpload(input.files[0]);
  const link = linkImporter(kind, async (ref) => {
    await fill();
    const f = S.files[kind].find((x) => x.ref === ref) || { ref, name: ref.split("/").pop().split("_").slice(1).join("_") };
    try { Object.assign(f, await api.get(`/api/probe?ref=${encodeURIComponent(ref)}`)); } catch {}
    choose(f);
  });
  const box = h("div", { class: "picker" }, thumb, h("div", { class: "info" }, name, sub, prog),
    h("div", { class: "btns" }, sel, h("button", { type: "button", class: "violet", onclick: () => input.click() }, "Upload"), input));
  const el = h("div", { class: "picker-wrap" }, box, link.el);
  box.addEventListener("dragover", (e) => { e.preventDefault(); box.classList.add("drag"); });
  box.addEventListener("dragleave", () => box.classList.remove("drag"));
  box.addEventListener("drop", (e) => {
    e.preventDefault(); box.classList.remove("drag");
    if (e.dataTransfer.files[0]) return doUpload(e.dataTransfer.files[0]);
    const u = (e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain") || "").trim().split("\n")[0];
    if (/^https?:\/\//.test(u)) link.setUrl(u);  // dragged a link from the browser
  });
  sub.textContent = "Drop a video or a link here, upload, or pick from your library";
  fill();
  w.el = el;
  return w;
}

function outputCard(o) {
  const isVid = /\.(mp4|webm|mov)$/i.test(o.file), isAud = /\.(mp3|wav|m4a)$/i.test(o.file), isImg = /\.(gif|jpg|png)$/i.test(o.file);
  const m = h("div", { class: "media" + (isAud ? " wide" : "") });
  if (isVid) m.append(h("video", { src: media(o.file), controls: true, preload: "metadata", poster: o.thumb ? media(o.thumb) : undefined, playsInline: true }));
  else if (isImg) m.append(h("img", { class: "full", src: media(o.file) }));
  else if (isAud) m.append(h("div", { style: { display: "grid", placeItems: "center", height: "100%", padding: "10px" } }, h("audio", { src: media(o.file), controls: true, style: { width: "100%" } })));
  if (o.score) m.append(h("span", { class: "badge" }, o.score));
  return h("div", { class: "card" }, m, h("div", { class: "body" },
    h("div", { class: "title", title: o.title }, o.title || o.file.split("/").pop()),
    h("div", { class: "meta" }, h("span", {}, o.duration ? fmtTime(o.duration) : ""), h("span", {}, o.start != null ? `${fmtTime(o.start)}–${fmtTime(o.end)}` : ""), o.framing ? h("span", { title: "Framing used" }, o.framing) : null),
    o.description || o.hashtags?.length ? h("div", { class: "desc" }, o.description || "", " ", h("span", { class: "tags" }, (o.hashtags || []).join(" "))) : null,
    h("div", { class: "btns" }, h("a", { href: media(o.file), download: "" }, h("button", { class: "sm primary" }, "Download")),
      o.srt ? h("a", { href: media(o.srt), download: "" }, h("button", { class: "sm" }, "SRT")) : null,
      o.description || o.hashtags?.length ? h("button", { class: "sm", onclick: () => { navigator.clipboard?.writeText(`${o.title}\n\n${o.description || ""}\n\n${(o.hashtags || []).join(" ")}`); toast("Caption copied"); } }, "Copy post text") : null)));
}

// ---------- job queue ----------
const Q = { jobs: new Map(), timer: null };
function trackJob(job, { onDone, onError, results } = {}) {
  Q.jobs.set(job.id, { job, onDone, onError, results });
  renderQueue();
  if (!Q.timer) Q.timer = setInterval(pollJobs, 1000);
}
async function pollJobs() {
  const active = [...Q.jobs.values()].filter((x) => ["queued", "running"].includes(x.job.status));
  if (!active.length) { clearInterval(Q.timer); Q.timer = null; return; }
  for (const x of active) {
    try {
      x.job = await api.get(`/api/jobs/${x.job.id}`);
      if (x.job.status === "done") {
        toast("✓ " + jobLabel(x.job) + " finished");
        setTimeout(refreshStatus, 1500);
        if (x.results) showResults(x.results, x.job.result.outputs);
        x.onDone && x.onDone(x.job.result);
        delete S.files.outputs;
      } else if (x.job.status === "error") {
        toast(jobLabel(x.job) + " failed: " + x.job.error, true);
        x.onError && x.onError(x.job.error);
      } else if (x.job.status === "cancelled") x.onError && x.onError("Cancelled");
    } catch {}
  }
  renderQueue();
}
function jobLabel(j) {
  return ({ analyze: "Find moments", render_clips: "Render clips", autoclip: "AutoClip", reddit: "Story video", faketext: "Fake texts",
    voiceover: "Voiceover", captions: "Auto captions", tool: "Tool: " + (j.params?.tool || ""), import_url: "Import", tts: "Voice" })[j.kind] || j.kind;
}
function renderQueue() {
  const items = [...Q.jobs.values()].map((x) => x.job).sort((a, b) => b.created - a.created).slice(0, 12);
  $("#queue").classList.toggle("show", items.length > 0);
  $("#queue-list").replaceChildren(...items.map((j) => h("div", { class: "qitem " + j.status },
    h("div", { class: "top" }, h("span", {}, jobLabel(j)),
      ["queued", "running"].includes(j.status)
        ? h("button", { class: "sm ghost danger", onclick: () => api.post(`/api/jobs/${j.id}/cancel`) }, "Cancel")
        : h("span", { class: "muted small" }, j.status === "done" ? "✓ done" : j.status)),
    h("div", { class: "msgline" }, j.status === "error" ? j.error : j.message),
    ["queued", "running"].includes(j.status) ? h("div", { class: "progress" }, h("i", { style: { width: j.progress * 100 + "%" } })) : null)));
}
$("#queue-toggle").onclick = (e) => { const q = $("#queue"); q.classList.toggle("min"); e.target.textContent = q.classList.contains("min") ? "Show" : "Hide"; };

async function startJob(kind, params, opts = {}) {
  const btn = opts.button;
  if (btn) { btn.disabled = true; btn.dataset.label = btn.textContent; btn.innerHTML = '<span class="spin"></span> Working…'; }
  const restore = () => { if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label; } };
  try {
    const job = await api.post(`/api/jobs/${kind}`, { params });
    trackJob(job, { ...opts, onDone: (r) => { restore(); opts.onDone && opts.onDone(r); }, onError: (e) => { restore(); opts.onError && opts.onError(e); } });
    return job;
  } catch (e) { restore(); toast(e.message, true); }
}
function showResults(el, outputs) {
  if (!outputs?.length) return;
  el.replaceChildren(h("h2", {}, "Results"), h("div", { class: "gallery" }, outputs.map(outputCard)));
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------- pages ----------
const PAGES = {};

PAGES.home = async (v) => {
  v.append(h("h1", {}, "What are we making today?"),
    h("p", { class: "lead" }, "Everything runs on your machine: local Whisper for transcripts, a local LLM for picking moments and writing scripts, free neural voices, and ffmpeg for rendering. No credits, no watermark."),
    h("div", { class: "hero" }, ROUTES.filter((r) => r.desc).map((r) =>
      h("a", { class: "tile", href: "#/" + r.id }, h("div", { class: "ico", style: { background: r.color }, html: icon(r.id) }), h("h3", {}, r.label), h("p", {}, r.desc)))));
  const outs = h("div", { class: "gallery" });
  v.append(h("div", { class: "btns", style: { justifyContent: "space-between", marginBottom: "14px" } }, h("h2", { style: { margin: 0 } }, "Recent exports"), h("a", { href: "#/library" }, h("button", { class: "sm" }, "Open library"))), outs);
  const files = (await loadFiles("outputs", true)).filter((f) => /\.(mp4|gif)$/.test(f.ref)).slice(0, 10);
  outs.replaceWith(files.length ? h("div", { class: "gallery" }, files.map((f) => outputCard({ file: f.ref, title: f.name, thumb: f.thumb?.replace("/media/", "") })))
    : h("div", { class: "empty" }, "Nothing exported yet — start with AutoClip or a Story video."));
};

// ---------- facecam box editor (modal) ----------
// rect is [x, y, w, h] as fractions of the source frame.
function facecamEditor({ file, info, rect, previewOpts, onSave }) {
  let r = rect ? [...rect] : null;
  const dur = info?.duration || 60;
  let t = Math.min(dur * 0.3, 60);
  const img = h("img", { draggable: false, alt: "Video frame" });
  const handles = ["nw", "n", "ne", "e", "se", "s", "sw", "w"].map((c) => h("i", { class: "hd " + c, "data-h": c }));
  const box = h("div", { class: "fcbox" }, handles);
  const stage = h("div", { class: "fc-stage" }, img, box);
  const coords = h("div", { class: "muted small" });
  const prev = h("img", { class: "preview916", alt: "Layout preview" });
  const prevNote = h("div", { class: "muted small" }, "Preview of the 9:16 result");
  const loadFrame = () => { img.src = `/api/frame?ref=${encodeURIComponent(file)}&t=${t.toFixed(2)}&w=1280`; };
  const draw = () => {
    box.style.display = r ? "" : "none";
    if (!r) { coords.textContent = "Drag on the frame to draw a box around the webcam."; return; }
    Object.assign(box.style, { left: r[0] * 100 + "%", top: r[1] * 100 + "%", width: r[2] * 100 + "%", height: r[3] * 100 + "%" });
    const W0 = info?.width || 1920, H0 = info?.height || 1080;
    coords.textContent = `x ${Math.round(r[0] * W0)}, y ${Math.round(r[1] * H0)} · ${Math.round(r[2] * W0)}×${Math.round(r[3] * H0)} px`;
  };
  let pt = null;
  const refreshPreview = () => {
    clearTimeout(pt);
    if (!r) return;
    pt = setTimeout(async () => {
      prevNote.textContent = "Rendering preview…";
      try {
        const res = await api.post("/api/layout/preview", { file, t, ...previewOpts(), layout: "facecam", facecam: "manual", facecam_rect: r });
        prev.src = res.url; prevNote.textContent = "Preview of the 9:16 result";
      } catch (e) { prevNote.textContent = e.message; }
    }, 350);
  };
  // drag: move / resize / draw new
  let drag = null;
  const at = (e) => { const b = stage.getBoundingClientRect(); return [Math.min(1, Math.max(0, (e.clientX - b.left) / b.width)), Math.min(1, Math.max(0, (e.clientY - b.top) / b.height))]; };
  stage.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    stage.setPointerCapture(e.pointerId);
    const p = at(e), hd = e.target.dataset?.h;
    if (hd && r) drag = { mode: "resize", hd, start: p, r0: [...r] };
    else if (e.target === box && r) drag = { mode: "move", start: p, r0: [...r] };
    else { drag = { mode: "resize", hd: "se", start: p, r0: [p[0], p[1], 0, 0] }; r = [p[0], p[1], 0.001, 0.001]; }
  });
  stage.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const [px, py] = at(e), dx = px - drag.start[0], dy = py - drag.start[1];
    let [x, y, w, hh] = drag.r0;
    if (drag.mode === "move") {
      x = Math.min(1 - w, Math.max(0, x + dx)); y = Math.min(1 - hh, Math.max(0, y + dy));
    } else {
      let x1 = x + w, y1 = y + hh;
      if (drag.hd.includes("w")) x = Math.min(px, x1 - 0.02);
      if (drag.hd.includes("e")) x1 = Math.max(px, x + 0.02);
      if (drag.hd.includes("n")) y = Math.min(py, y1 - 0.02);
      if (drag.hd.includes("s")) y1 = Math.max(py, y + 0.02);
      w = x1 - x; hh = y1 - y;
    }
    r = [x, y, w, hh];
    draw();
  });
  const end = () => { if (!drag) return; drag = null; if (r && (r[2] < 0.02 || r[3] < 0.02)) r = null; draw(); refreshPreview(); };
  stage.addEventListener("pointerup", end);
  stage.addEventListener("pointercancel", end);

  const scrub = h("input", { type: "range", min: 0, max: dur, step: 0.5, value: t, onchange: (e) => { t = +e.target.value; tl.textContent = fmtTime(t); loadFrame(); refreshPreview(); } });
  const tl = h("span", { class: "muted small" }, fmtTime(t));
  const detectBtn = h("button", { onclick: async () => {
    detectBtn.disabled = true; detectBtn.textContent = "Detecting… (first time ~15s)";
    try {
      const res = await api.post("/api/facecam/detect", { file });
      if (res.rect) { r = res.rect; draw(); refreshPreview(); toast("Facecam found. Adjust the box if needed."); }
      else toast("No facecam found. Draw the box yourself.", true);
    } catch (e) { toast(e.message, true); }
    detectBtn.disabled = false; detectBtn.textContent = "🔍 Auto-detect";
  } }, "🔍 Auto-detect");
  const close = () => { bg.remove(); document.removeEventListener("keydown", esc); };
  const esc = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", esc);
  const bg = h("div", { class: "modal-bg", onclick: (e) => { if (e.target === bg) close(); } },
    h("div", { class: "modal" },
      h("div", { class: "btns", style: { justifyContent: "space-between", marginBottom: "10px" } },
        h("h2", { style: { margin: 0 } }, "Facecam box"), h("button", { class: "sm", onclick: close }, "✕")),
      h("p", { class: "muted small", style: { marginTop: 0 } }, "Draw or drag the box so it covers only the webcam, with no gameplay inside. Drag the corners or edges to resize. Scrub to any moment to check it."),
      h("div", { class: "fc-wrap" },
        h("div", {}, stage, h("div", { class: "btns", style: { marginTop: "10px", alignItems: "center" } }, h("span", { class: "muted small" }, "Frame"), scrub, tl), coords),
        h("div", {}, prev, prevNote)),
      h("div", { class: "btns", style: { marginTop: "14px" } }, detectBtn,
        h("button", { onclick: () => { r = null; draw(); } }, "Clear"),
        h("button", { class: "primary", onclick: () => { if (!r) return toast("Draw the facecam box first", true); onSave(r.map((v) => +v.toFixed(4))); close(); } }, "Use this box"),
        h("button", { onclick: close }, "Cancel"))));
  document.body.append(bg);
  loadFrame(); draw(); refreshPreview();
  if (!r) detectBtn.click();  // start from the auto-detected box
}

PAGES.autoclip = async (v) => {
  v.append(h("h1", {}, "AutoClip"), h("p", { class: "lead" }, "Pick what kind of video it is. Each type has its own detection engine: podcasts are clipped from what is said, gameplay and trailers from the action itself (game audio, motion, scene cuts, reactions) with an AI that watches the candidates."));
  const P = await api.get("/api/presets");
  const LANGS = [["", "Auto-detect"], ["en", "English"], ["es", "Spanish"], ["fr", "French"], ["de", "German"], ["pt", "Portuguese"], ["it", "Italian"], ["ar", "Arabic"], ["hi", "Hindi"], ["ja", "Japanese"], ["ru", "Russian"], ["tr", "Turkish"]];
  let ctype = store.get("ctype", "gameplay");
  let cfg = null;          // live config for the selected type
  let analysis = null;
  const loadCfg = (t) => {
    const d = P.types[t].defaults, saved = store.get("cfg_" + t, {});
    return { ...d, ...saved, weights: { ...d.weights, ...(saved.weights || {}) } };
  };
  const saveCfg = () => { store.set("cfg_" + ctype, cfg); schedulePreview(); };

  // ---- live 9:16 layout preview ----
  const PREVIEW_LAYOUTS = ["facecam", "zoom", "fit", "center"];
  const prevImg = h("img", { class: "preview916", alt: "Layout preview", style: { display: "none" } });
  const prevMsg = h("div", { class: "muted small" });
  let previewOn = false, prevTimer = null;
  const previewOpts = () => ({ facecam_size: cfg.facecam_size, gameplay_fit: cfg.gameplay_fit, facecam_fit: cfg.facecam_fit, facecam_pos: cfg.facecam_pos });
  async function doPreview() {
    if (!picker.value) { prevMsg.textContent = "Pick a video to preview the layout."; return; }
    if (!PREVIEW_LAYOUTS.includes(cfg.layout)) { prevMsg.textContent = "Preview is available for facecam, zoom, full-frame and center layouts."; return; }
    previewOn = true;
    prevMsg.textContent = cfg.layout === "facecam" && cfg.facecam !== "manual" ? "Finding the facecam and rendering… (first time ~15s)" : "Rendering…";
    try {
      const res = await api.post("/api/layout/preview", { file: picker.value, t: player.currentTime || null, layout: cfg.layout,
        facecam: cfg.facecam, facecam_rect: cfg.facecam_rect, ...previewOpts() });
      prevImg.src = res.url; prevImg.style.display = "";
      prevMsg.textContent = cfg.layout === "facecam" ? (res.facecam ? `Facecam: ${res.facecam.corner === "manual" ? "your box" : "auto-detected (" + res.facecam.corner + ")"}. Frame at the player's position.` : "No facecam found. Use “Adjust / draw facecam” to mark it.") : "Frame at the player's position.";
    } catch (e) { prevMsg.textContent = e.message; }
  }
  function schedulePreview() { if (!previewOn) return; clearTimeout(prevTimer); prevTimer = setTimeout(doPreview, 400); }
  const openEditor = async (initRect) => {
    if (!picker.value) return toast("Pick a video first", true);
    let info = picker.info;
    if (!info?.width) { try { info = await api.get(`/api/probe?ref=${encodeURIComponent(picker.value)}`); } catch {} }
    let rect = initRect || cfg.facecam_rect || null;
    if (!rect && analysis?.facecam?.rect && info?.width) { const [x, y, w, hh] = analysis.facecam.rect; rect = [x / info.width, y / info.height, w / info.width, hh / info.height]; }
    facecamEditor({ file: picker.value, info, rect, previewOpts, onSave: (r) => {
      cfg.facecam = "manual"; cfg.facecam_rect = r; previewOn = true; saveCfg();
      if (analysis) { analysis.facecam = null; drawMoments(); }
      drawSettings(); toast("Facecam box saved. Clips will use it.");
    } });
  };

  // ---- step 1: type picker ----
  const typeCards = h("div", { class: "pcards", style: { marginBottom: "18px" } });
  const drawTypes = () => typeCards.replaceChildren(...Object.entries(P.types).map(([id, t]) =>
    h("button", { type: "button", class: "pcard" + (ctype === id ? " on" : ""), onclick: () => { ctype = id; store.set("ctype", id); analysis = null; momentsEl.replaceChildren(); drawTypes(); drawSettings(); } },
      h("div", { class: "ptitle" }, `${t.emoji} ${t.label}`), h("div", { class: "pdesc" }, t.desc))));

  // ---- source ----
  const player = h("video", { class: "player", controls: true, preload: "metadata", style: { display: "none" } });
  const picker = videoPicker((f) => { player.style.display = f ? "" : "none"; player.src = f ? media(f.ref) : ""; schedulePreview(); });

  // ---- step 2: type-specific settings ----
  const settingsPanel = h("div", { class: "panel" });
  const num = (key, min, max) => h("input", { type: "number", value: cfg[key], min, max, oninput: (e) => { cfg[key] = +e.target.value; saveCfg(); } });
  const check = (key, label, extra) => h("label", { class: "check", style: { marginBottom: "10px" } },
    h("input", { type: "checkbox", checked: !!cfg[key], onchange: (e) => { cfg[key] = e.target.checked; saveCfg(); drawSettings(); } }), label, extra || null);
  const slider = (key, label, hint) => {
    const out = h("span", { class: "muted small" }, (+cfg.weights[key]).toFixed(1));
    const r = h("input", { type: "range", min: 0, max: 2, step: 0.1, value: cfg.weights[key], oninput: (e) => { cfg.weights[key] = +e.target.value; out.textContent = (+e.target.value).toFixed(1); saveCfg(); } });
    return h("div", { class: "field" }, h("label", {}, label, " ", out), r, h("div", { class: "hint", style: { marginTop: 0 } }, hint));
  };
  const segField = (key, label, options, hint, redraw) => field(label, seg(options, cfg[key], (x) => { cfg[key] = x; saveCfg(); if (redraw) drawSettings(); }), hint);

  function drawSettings() {
    cfg = loadCfg(ctype);
    const T = P.types[ctype];
    const isSignals = T.engine === "signals";
    const parts = [h("h2", {}, `${T.emoji} ${T.label} settings`)];
    parts.push(h("div", { class: "row" }, field("Clips", num("count", 1, 20)), field("Min length (s)", num("min_len", 5, 170)), field("Max length (s)", num("max_len", 8, 180))));
    if (isSignals) {
      parts.push(field("Game / topic", h("input", { type: "text", value: cfg.game || "", placeholder: "e.g. GTA 6", oninput: (e) => { cfg.game = e.target.value; saveCfg(); } }), "Used for titles and hashtags."));
      parts.push(check("transcribe", "Transcribe speech (commentary captions + reaction detection)"));
    }
    if (!isSignals || cfg.transcribe) {
      const lang = h("select", { onchange: (e) => { cfg.language = e.target.value || null; saveCfg(); } }, LANGS.map(([a, b]) => h("option", { value: a, selected: (cfg.language || "") === a }, b)));
      parts.push(field("Spoken language", lang));
    }
    if (isSignals) {
      parts.push(h("div", { class: "lbl", style: { margin: "6px 0 10px" } }, "What counts as a highlight"));
      parts.push(slider("action", "Action audio", "Gunfire, explosions, crashes, sudden loud moments."));
      parts.push(slider("motion", "Motion", "Chases, fights, fast camera."));
      if (cfg.transcribe) parts.push(slider("reactions", "Reactions", "Streamer shouting, laughing, “no way”, “bro”…"));
      parts.push(slider("cuts", "Scene cuts", "Fast editing. Raise for trailers and montages."));
      parts.push(check("snap_cuts", "Start and end clips exactly on scene cuts"));
    }
    const aiLabel = S.status?.llm_model ? ` · ${S.status.llm_provider_label}: ${S.status.llm_model}` : " · no AI configured";
    parts.push(check("use_ai", isSignals ? "Use AI to rank highlights and write titles" : "Use AI to pick moments", h("span", { class: "muted small" }, aiLabel)));
    if (isSignals && cfg.use_ai) {
      parts.push(P.vision ? check("vision", "AI watches each candidate (contact sheets of frames)", h("span", { class: "muted small" }, " · best for gameplay"))
        : h("p", { class: "hint" }, "Your current AI can't see images. Pick Claude or a vision model in ", h("a", { href: "#/settings", style: { color: "var(--accent)" } }, "AI Settings"), " to let it watch gameplay."));
    }
    parts.push(segField("layout", "Layout", T.layouts.map((l) => [l, P.layouts[l]]), null, true));
    if (cfg.layout === "facecam") {
      if (typeof cfg.facecam_size !== "number") cfg.facecam_size = { small: 25, medium: 33, large: 40 }[cfg.facecam_size] || 33;
      if (!["auto", "manual"].includes(cfg.facecam)) cfg.facecam = "auto";
      if (cfg.facecam === "manual" && !cfg.facecam_rect) cfg.facecam = "auto";
      const sizeOut = h("span", { class: "muted small" }, cfg.facecam_size + "%");
      const size = h("input", { type: "range", min: 15, max: 60, step: 1, value: cfg.facecam_size,
        oninput: (e) => { cfg.facecam_size = +e.target.value; sizeOut.textContent = cfg.facecam_size + "%"; }, onchange: () => saveCfg() });
      const fcHint = cfg.facecam === "manual" ? "Using your box. Click “Adjust” to change it." : "Found automatically by scanning for a fixed webcam. Check it with Preview; if it's off, adjust it.";
      parts.push(h("div", { class: "subpanel" },
        h("div", { class: "lbl", style: { marginBottom: "10px" } }, "Facecam"),
        h("div", { class: "btns", style: { alignItems: "center", marginBottom: "6px" } },
          seg([["auto", "Auto-detect"], ...(cfg.facecam_rect ? [["manual", "My box"]] : [])], cfg.facecam, (x) => { cfg.facecam = x; saveCfg(); drawSettings(); }).el,
          h("button", { onclick: () => openEditor() }, "✏️ Adjust / draw facecam")),
        h("div", { class: "hint", style: { margin: "0 0 14px" } }, fcHint),
        h("div", { class: "row", style: { alignItems: "flex-start" } },
          segField("facecam_pos", "Facecam goes", [["top", "On top"], ["bottom", "At the bottom"]]),
          segField("facecam_fit", "Facecam fit", [["blur", "Whole cam + blur"], ["fill", "Fill (crop/zoom)"]])),
        h("div", { class: "row", style: { alignItems: "flex-start" } },
          h("div", { class: "field" }, h("label", {}, "Facecam height ", sizeOut), size),
          segField("gameplay_fit", "Gameplay", [["crop", "Fill (crop sides)"], ["fit", "Whole frame + blur"]]))));
    }
    if (isSignals && PREVIEW_LAYOUTS.includes(cfg.layout)) {
      parts.push(h("div", { class: "subpanel layout-prev" },
        h("div", {}, h("div", { class: "lbl", style: { marginBottom: "8px" } }, "Layout preview"),
          h("button", { class: "sm", onclick: doPreview }, "👁 Preview layout"), prevMsg), prevImg));
    }
    const style = styleTiles(cfg.style);
    style.el.addEventListener("click", () => { cfg.style = style.value; saveCfg(); });
    parts.push(field("Captions", style, isSignals && !cfg.transcribe ? "Captions need speech. Turn on “Transcribe speech” to use them." : null));
    parts.push(h("div", { class: "row" }, segField("position", "Caption position", [["upper", "Upper"], ["middle", "Middle"], ["lower", "Lower"], ["bottom", "Bottom"]]),
      segField("title_mode", "Hook title", [["intro", "First 4s"], ["always", "Always"], ["none", "None"]])));
    parts.push(h("div", { class: "btns" }, analyzeBtn, autoBtn),
      h("p", { class: "muted small" }, "“Find highlights” lets you review, preview and edit clips first. One-click renders the top picks directly."));
    settingsPanel.replaceChildren(...parts);
  }

  const momentsEl = h("div");
  const results = h("div", { class: "results" });
  const need = () => { if (!picker.value) { toast("Pick a video first", true); return false; } return true; };
  const renderOpts = () => ({ content_type: ctype, style: cfg.style, position: cfg.position, reframe_mode: cfg.layout, title_mode: cfg.title_mode,
    facecam: analysis?.facecam || null, facecam_mode: cfg.facecam || "auto", facecam_rect: cfg.facecam_rect || null,
    facecam_size: cfg.facecam_size || 33, facecam_fit: cfg.facecam_fit || "blur", facecam_pos: cfg.facecam_pos || "top", gameplay_fit: cfg.gameplay_fit || "crop" });
  const analyzeBtn = h("button", { class: "violet", onclick: () => need() && startJob("analyze", { file: picker.value, content_type: ctype, config: cfg },
    { button: analyzeBtn, onDone: (r) => { analysis = r; drawMoments(); } }) }, "Find highlights");
  const autoBtn = h("button", { class: "primary", onclick: () => need() && startJob("autoclip", { file: picker.value, content_type: ctype, config: cfg },
    { button: autoBtn, results, onDone: (r) => { analysis = r; drawMoments(); } }) }, "⚡ One-click AutoClip");

  let stopAt = null;
  player.addEventListener("timeupdate", () => { if (stopAt != null && player.currentTime >= stopAt) { player.pause(); stopAt = null; } });

  function drawMoments() {
    if (!analysis) return;
    const ms = analysis.moments;
    ms.forEach((m) => (m.on ??= true));
    const renderBtn = h("button", { class: "primary", onclick: () => {
      const clips = ms.filter((m) => m.on).map(({ start, end, title, score, description, hashtags }) => ({ start: +start, end: +end, title, score, description, hashtags }));
      if (!clips.length) return toast("Select at least one clip", true);
      startJob("render_clips", { file: analysis.file, clips, ...renderOpts() }, { button: renderBtn, results });
    } }, "Render selected clips");
    const addBtn = h("button", { onclick: () => {
      const t = player.currentTime || 0;
      ms.push({ id: ms.length + 1, start: +t.toFixed(2), end: +Math.min(t + 30, analysis.duration).toFixed(2), title: "", score: null, text: "Manual clip", on: true });
      drawMoments();
    } }, "+ Add manual clip at playhead");
    const fc = analysis.facecam;
    const info = cfg.layout === "facecam" ? h("div", { class: "btns", style: { alignItems: "center", marginBottom: "10px" } },
      h("span", { class: (fc || cfg.facecam === "manual") ? "ok small" : "err small" },
        cfg.facecam === "manual" ? "✓ Using your facecam box" : fc ? `✓ Facecam found (${fc.corner})` : "No facecam detected. Draw it yourself, or use Zoomed gameplay."),
      h("button", { class: "sm", onclick: () => openEditor() }, "✏️ Adjust facecam")) : null;
    momentsEl.replaceChildren(h("div", { class: "panel", style: { marginTop: "18px" } },
      h("div", { class: "btns", style: { justifyContent: "space-between", marginBottom: "14px" } },
        h("h2", { style: { margin: 0 } }, `${ms.length} highlights found`), h("div", { class: "btns" }, addBtn, renderBtn)), info,
      ms.length ? ms.map((m) => {
        const s = h("input", { type: "number", step: "0.1", value: m.start, oninput: (e) => (m.start = +e.target.value) });
        const e = h("input", { type: "number", step: "0.1", value: m.end, oninput: (ev) => (m.end = +ev.target.value) });
        const row = h("div", { class: "moment" + (m.on ? "" : " off") },
          h("input", { type: "checkbox", checked: m.on, style: { accentColor: "var(--accent)", width: "18px", height: "18px" }, onchange: (ev) => { m.on = ev.target.checked; row.classList.toggle("off", !m.on); } }),
          h("div", {},
            h("div", { class: "btns", style: { justifyContent: "space-between" } },
              h("span", { class: "score" }, m.score ? `★ ${m.score}/100` : "Manual"),
              h("span", { class: "muted small" }, `${fmtTime(m.start)} → ${fmtTime(m.end)} · ${Math.round(m.end - m.start)}s`)),
            h("input", { type: "text", value: m.title || "", placeholder: "Hook title shown on the clip", oninput: (ev) => (m.title = ev.target.value), style: { marginTop: "6px" } }),
            h("div", { class: "txt" }, m.reason ? h("b", {}, m.reason + " — ") : null, m.text || ""),
            m.hashtags?.length ? h("div", { class: "muted small" }, (m.source ? `${m.source} · ` : "") + m.hashtags.join(" ")) : null,
            h("div", { class: "row" }, h("div", { class: "field", style: { marginBottom: 0 } }, h("label", {}, "Start (s)"), s),
              h("div", { class: "field", style: { marginBottom: 0 } }, h("label", {}, "End (s)"), e),
              h("button", { class: "sm", onclick: () => { player.currentTime = m.start; stopAt = m.end; player.play(); } }, "▶ Preview"),
              h("button", { class: "sm", onclick: () => { m.start = +player.currentTime.toFixed(2); s.value = m.start; } }, "Set start"),
              h("button", { class: "sm", onclick: () => { m.end = +player.currentTime.toFixed(2); e.value = m.end; } }, "Set end"))));
        return row;
      }) : h("div", { class: "empty" }, "No clear highlights found. Try raising the sliders, or add clips manually from the player.")));
  }

  drawTypes();
  drawSettings();
  v.append(h("h2", {}, "1. What kind of video is it?"), typeCards,
    h("div", { class: "grid cols-2" },
      h("div", { class: "panel" }, h("h2", {}, "2. Source video"), picker.el, h("div", { style: { marginTop: "14px" } }, player)),
      settingsPanel),
    momentsEl, results);
};

PAGES.story = (v) => {
  v.append(h("h1", {}, "Story Videos"), h("p", { class: "lead" }, "Paste a story (or let the local AI write one). It gets narrated, the title appears as a post card, and captions pop word by word over your gameplay footage."));
  const title = h("input", { type: "text", placeholder: "AITA for refusing to…" });
  const body = h("textarea", { rows: 10, placeholder: "The story text…" });
  const sub = h("input", { type: "text", value: "r/AskReddit" });
  const user = h("input", { type: "text", value: "throwaway_" + Math.floor(Math.random() * 9000 + 1000) });
  const idea = h("input", { type: "text", placeholder: "Idea for AI, e.g. 'roommate steals my food, petty revenge'" });
  const aiBtn = h("button", { class: "violet", onclick: async () => {
    aiBtn.disabled = true; aiBtn.innerHTML = '<span class="spin"></span> Writing…';
    try { const r = await api.post("/api/ai/write", { kind: "reddit", prompt: idea.value }); title.value = r.title; body.value = r.body; sub.value = r.subreddit || sub.value; }
    catch (e) { toast(e.message, true); }
    aiBtn.disabled = false; aiBtn.textContent = "✨ Write with AI";
  } }, "✨ Write with AI");
  const voice = voiceSelect("en-US-AndrewMultilingualNeural");
  const speed = h("input", { type: "range", min: 0.8, max: 1.5, step: 0.05, value: 1.15 });
  const speedL = h("span", { class: "muted small" }, "1.15×"); speed.oninput = () => (speedL.textContent = speed.value + "×");
  const bg = libSelect("backgrounds", { extra: [["gradient", "Animated gradient (built-in)"], ["random", "Random from my backgrounds"]] });
  const music = libSelect("music", { accept: "audio/*", extra: [["none", "No music"], ["random", "Random from my music"]] });
  const style = styleTiles("bold");
  const pos = seg([["upper", "Upper"], ["middle", "Middle"], ["lower", "Lower"]], "middle");
  const theme = seg([["light", "Light card"], ["dark", "Dark card"]], "light");
  const readTitle = h("input", { type: "checkbox", checked: true });
  const results = h("div", { class: "results" });
  const go = h("button", { class: "primary", onclick: () => {
    if (!body.value.trim()) return toast("Write or generate a story first", true);
    startJob("reddit", { title: title.value, body: body.value, community: sub.value, username: user.value, voice: voice.value, speed: +speed.value,
      background: bg.value, music: music.value, style: style.value, position: pos.value, card_theme: theme.value, read_title: readTitle.checked }, { button: go, results });
  } }, "Generate video");
  v.append(h("div", { class: "grid cols-2" },
    h("div", { class: "panel" }, h("h2", {}, "Story"), h("div", { class: "row" }, h("div", { class: "field", style: { flex: 3 } }, idea), h("div", { class: "field", style: { flex: "none" } }, aiBtn)),
      field("Title", title), field("Body", body), h("div", { class: "row" }, field("Community", sub), field("Username", user)),
      h("label", { class: "check" }, readTitle, "Read the title aloud and show the post card")),
    h("div", { class: "panel" }, h("h2", {}, "Voice & look"), field("Narrator", voice), field(h("span", {}, "Speed ", speedL), speed),
      field("Background footage", bg, "Upload your own gameplay clips (parkour, satisfying, etc.) to Backgrounds."), field("Music", music),
      field("Captions", style), h("div", { class: "row" }, field("Position", pos), field("Card", theme)), go)), results);
};

PAGES.texts = (v) => {
  v.append(h("h1", {}, "Fake Texts"), h("p", { class: "lead" }, "Script a text conversation. Each message pops in with its own voice over background footage."));
  const contact = h("input", { type: "text", value: "Mom" });
  let msgs = [{ from: "them", text: "Why is there a goat in the backyard" }, { from: "me", text: "What goat" }, { from: "them", text: "The one eating my roses" },
    { from: "me", text: "Oh that's Kevin" }, { from: "them", text: "WHO IS KEVIN" }, { from: "me", text: "He's emotional support. For the roses." }];
  const list = h("div");
  const draw = () => list.replaceChildren(...msgs.map((m, i) => h("div", { class: "msg" },
    h("button", { type: "button", class: "who " + m.from, onclick: () => { m.from = m.from === "me" ? "them" : "me"; draw(); } }, m.from === "me" ? "Me" : "Them"),
    h("input", { type: "text", value: m.text, oninput: (e) => (m.text = e.target.value) }),
    h("button", { class: "sm ghost", title: "Move up", onclick: () => { if (i) { [msgs[i - 1], msgs[i]] = [msgs[i], msgs[i - 1]]; draw(); } } }, "↑"),
    h("button", { class: "sm ghost danger", onclick: () => { msgs.splice(i, 1); draw(); } }, "✕"))));
  draw();
  const idea = h("input", { type: "text", placeholder: "Idea for AI, e.g. 'texting my landlord about a broken sink'" });
  const aiBtn = h("button", { class: "violet", onclick: async () => {
    aiBtn.disabled = true; aiBtn.innerHTML = '<span class="spin"></span> Writing…';
    try { const r = await api.post("/api/ai/write", { kind: "faketext", prompt: idea.value }); msgs = r.messages; contact.value = r.contact; draw(); }
    catch (e) { toast(e.message, true); }
    aiBtn.disabled = false; aiBtn.textContent = "✨ Write with AI";
  } }, "✨ Write with AI");
  const vMe = voiceSelect("en-US-AndrewMultilingualNeural"), vThem = voiceSelect("en-US-AvaMultilingualNeural");
  const theme = seg([["light", "Light"], ["dark", "Dark"]], "dark");
  const bg = libSelect("backgrounds", { extra: [["gradient", "Animated gradient (built-in)"], ["random", "Random from my backgrounds"]] });
  const music = libSelect("music", { accept: "audio/*", extra: [["none", "No music"], ["random", "Random from my music"]] });
  const results = h("div", { class: "results" });
  const go = h("button", { class: "primary", onclick: () => startJob("faketext", { messages: msgs, contact: contact.value, voice_me: vMe.value,
    voice_them: vThem.value, theme: theme.value, background: bg.value, music: music.value }, { button: go, results }) }, "Generate video");
  v.append(h("div", { class: "grid cols-2" },
    h("div", { class: "panel" }, h("h2", {}, "Conversation"), h("div", { class: "row" }, h("div", { class: "field", style: { flex: 3 } }, idea), h("div", { class: "field", style: { flex: "none" } }, aiBtn)),
      field("Contact name", contact), h("div", { class: "lbl", style: { marginBottom: "8px" } }, "Messages (tap Me/Them to switch sender)"), list,
      h("button", { class: "sm", onclick: () => { msgs.push({ from: msgs.at(-1)?.from === "me" ? "them" : "me", text: "" }); draw(); list.lastChild?.querySelector("input")?.focus(); } }, "+ Add message")),
    h("div", { class: "panel" }, h("h2", {}, "Voices & look"), field("My voice", vMe), field("Their voice", vThem), field("Chat theme", theme),
      field("Background footage", bg), field("Music", music), go)), results);
};

PAGES.voiceover = (v) => {
  v.append(h("h1", {}, "AI Voiceover"), h("p", { class: "lead" }, "Write a script, pick a voice, and narrate it over your own video or background footage — with synced captions."));
  const script = h("textarea", { rows: 9, placeholder: "Your script…" });
  const idea = h("input", { type: "text", placeholder: "Topic for AI, e.g. '3 facts about octopuses'" });
  const aiBtn = h("button", { class: "violet", onclick: async () => {
    aiBtn.disabled = true; aiBtn.innerHTML = '<span class="spin"></span> Writing…';
    try { script.value = (await api.post("/api/ai/write", { kind: "script", prompt: idea.value })).script; } catch (e) { toast(e.message, true); }
    aiBtn.disabled = false; aiBtn.textContent = "✨ Write with AI";
  } }, "✨ Write with AI");
  const voice = voiceSelect("en-US-AndrewMultilingualNeural");
  const speed = h("input", { type: "range", min: 0.7, max: 1.5, step: 0.05, value: 1 });
  const source = seg([["bg", "Background footage"], ["video", "My video"], ["audio", "Audio only (MP3)"]], "bg", (x) => { bgF.style.display = x === "bg" ? "" : "none"; vidF.style.display = x === "video" ? "" : "none"; vidOpts.style.display = x === "video" ? "" : "none"; });
  const bg = libSelect("backgrounds", { extra: [["gradient", "Animated gradient (built-in)"], ["random", "Random from my backgrounds"]] });
  const vid = libSelect("uploads", {});
  const audioMode = seg([["replace", "Replace original audio"], ["mix", "Mix with original"]], "replace");
  const layout = seg([["vertical", "Make vertical 9:16"], ["keep", "Keep size"]], "vertical");
  const style = styleTiles("bold");
  const music = libSelect("music", { accept: "audio/*", extra: [["none", "No music"], ["random", "Random from my music"]] });
  const bgF = field("Background", bg), vidF = field("Video", vid);
  const vidOpts = h("div", {}, field("Original audio", audioMode), field("Layout", layout));
  vidF.style.display = vidOpts.style.display = "none";
  const results = h("div", { class: "results" });
  const go = h("button", { class: "primary", onclick: () => {
    if (!script.value.trim()) return toast("Write a script first", true);
    if (source.value === "audio") return startJob("tts", { text: script.value, voice: voice.value, speed: +speed.value }, { button: go, results });
    startJob("voiceover", { script: script.value, voice: voice.value, speed: +speed.value, video: source.value === "video" ? vid.value : null,
      background: bg.value, audio_mode: audioMode.value, layout: layout.value, style: style.value, music: music.value }, { button: go, results });
  } }, "Generate");
  v.append(h("div", { class: "grid cols-2" },
    h("div", { class: "panel" }, h("h2", {}, "Script"), h("div", { class: "row" }, h("div", { class: "field", style: { flex: 3 } }, idea), h("div", { class: "field", style: { flex: "none" } }, aiBtn)),
      field("Script", script), field("Voice", voice), field("Speed", speed)),
    h("div", { class: "panel" }, h("h2", {}, "Output"), field("Visuals", source), bgF, vidF, vidOpts, field("Captions", style), field("Music", music), go)), results);
};

PAGES.captions = (v) => {
  v.append(h("h1", {}, "Auto Captions"), h("p", { class: "lead" }, "Transcribe any video locally and burn in animated captions. Also exports an .srt file."));
  const picker = videoPicker();
  const style = styleTiles("karaoke");
  const pos = seg([["upper", "Upper"], ["middle", "Middle"], ["lower", "Lower"], ["bottom", "Bottom"]], "lower");
  const layout = seg([["keep", "Keep original size"], ["auto", "9:16 auto (speaker + split)"], ["face", "9:16 follow speaker"], ["zoom", "9:16 zoomed gameplay"], ["fit", "9:16 fit + blur"], ["center", "9:16 center"]], "keep");
  const size = h("input", { type: "range", min: 0.6, max: 1.6, step: 0.05, value: 1 });
  const results = h("div", { class: "results" });
  const go = h("button", { class: "primary", onclick: () => picker.value ? startJob("captions", { file: picker.value, style: style.value === "none" ? "minimal" : style.value,
    position: pos.value, layout: layout.value, size_scale: +size.value }, { button: go, results }) : toast("Pick a video first", true) }, "Add captions");
  v.append(h("div", { class: "grid cols-2" }, h("div", { class: "panel" }, h("h2", {}, "Video"), picker.el),
    h("div", { class: "panel" }, field("Caption style", style), field("Position", pos), field("Layout", layout), field("Text size", size), go)), results);
};

const TOOL_FORMS = {
  trim: [["start", "Start (s)", 0], ["end", "End (s)", ""]],
  compress: [["quality", "Quality", "medium", [["high", "High"], ["medium", "Balanced"], ["low", "Smallest"]]], ["target_mb", "Or target size (MB, optional)", ""], ["max_height", "Max height (px)", 1080]],
  gif: [["start", "Start (s)", 0], ["end", "End (s)", 5], ["fps", "FPS", 12], ["width", "Width (px)", 480]],
  speed: [["factor", "Speed factor (0.25–4)", 1.5]],
  aspect: [["ratio", "Ratio", "9:16", [["9:16", "9:16"], ["1:1", "1:1"], ["4:5", "4:5"], ["16:9", "16:9"], ["4:3", "4:3"]]], ["mode", "Mode", "fit", [["fit", "Fit + blurred fill"], ["crop", "Crop to fill"]]]],
  volume: [["gain_db", "Gain (dB)", 6]],
  thumbnail: [["time", "Time (s)", 1]],
};
const TOOL_DESC = { trim: "Cut a section out of a video.", compress: "Shrink file size, optionally to a target MB.", gif: "Convert a section to a high-quality GIF.",
  speed: "Speed up or slow down video and audio.", reverse: "Play a video backwards (≤ 2 min).", mute: "Strip the audio track.", mp3: "Extract audio as MP3.",
  mp4: "Convert any format to MP4 (H.264/AAC).", merge: "Join multiple videos end to end.", aspect: "Convert to 9:16, 1:1, 4:5 or 16:9.",
  volume: "Make quiet videos louder without clipping.", enhance: "Remove noise and even out speech.", balance: "Normalize loudness to platform level.", thumbnail: "Grab a full-res frame." };

PAGES.tools = (v, arg) => {
  v.append(h("h1", {}, "Free Tools"), h("p", { class: "lead" }, "Quick ffmpeg-powered utilities. Unlimited and free."));
  const tools = S.status?.tools || {};
  const id = arg && tools[arg] ? arg : null;
  if (!id) {
    v.append(h("div", { class: "hero" }, Object.entries(tools).map(([k, label]) =>
      h("a", { class: "tile", href: "#/tools/" + k }, h("h3", {}, label), h("p", {}, TOOL_DESC[k] || "")))));
    return;
  }
  v.append(h("a", { href: "#/tools", class: "muted small" }, "← All tools"), h("h2", { style: { marginTop: "10px" } }, tools[id]));
  const results = h("div", { class: "results" });
  const ctrls = {};
  let picker, multi;
  const form = h("div", { class: "panel" });
  if (id === "merge") {
    multi = []; const list = h("div");
    const sel = libSelect("uploads", {});
    const draw = () => list.replaceChildren(...multi.map((r, i) => h("div", { class: "btns", style: { marginBottom: "6px" } }, h("span", {}, `${i + 1}. ${r.split("/").pop().split("_").slice(1).join("_")}`),
      h("button", { class: "sm ghost danger", onclick: () => { multi.splice(i, 1); draw(); } }, "✕"))));
    form.append(field("Add videos in order", h("div", { class: "btns" }, sel.el, h("button", { class: "sm violet", onclick: () => { if (sel.value) { multi.push(sel.value); draw(); } } }, "Add"))), list);
  } else {
    picker = videoPicker();
    form.append(picker.el, h("div", { style: { height: "16px" } }));
  }
  const row = h("div", { class: "row" });
  for (const [k, label, def, choices] of TOOL_FORMS[id] || []) {
    ctrls[k] = choices ? h("select", {}, choices.map(([a, b]) => h("option", { value: a, selected: a === def }, b))) : h("input", { type: "number", step: "any", value: def });
    row.append(field(label, ctrls[k]));
  }
  form.append(row);
  const go = h("button", { class: "primary", onclick: () => {
    const params = { tool: id };
    for (const [k, el] of Object.entries(ctrls)) if (el.value !== "") params[k] = isNaN(+el.value) ? el.value : +el.value;
    if (id === "merge") params.files = multi; else { if (!picker.value) return toast("Pick a file first", true); params.file = picker.value; }
    startJob("tool", params, { button: go, results });
  } }, "Run " + tools[id]);
  form.append(go);
  v.append(form, results);
};

PAGES.library = async (v, arg) => {
  const kind = ["uploads", "backgrounds", "music", "outputs"].includes(arg) ? arg : "uploads";
  v.append(h("h1", {}, "Library"), h("p", { class: "lead" }, "Your source videos, background gameplay, music and exports. Everything lives in the data/ folder."));
  v.append(h("div", { class: "tabs seg" }, [["uploads", "Videos"], ["backgrounds", "Backgrounds"], ["music", "Music"], ["outputs", "Exports"]].map(([k, l]) =>
    h("a", { href: "#/library/" + k }, h("button", { class: k === kind ? "on" : "" }, l)))));
  if (kind !== "outputs") {
    const up = h("input", { type: "file", multiple: true, accept: kind === "music" ? "audio/*" : "video/*", hidden: true, onchange: async () => {
      for (const f of up.files) { try { await uploadFile(f, kind, (p) => (upBtn.textContent = `Uploading ${Math.round(p * 100)}%`)); } catch (e) { toast(e.message, true); } }
      upBtn.textContent = "Upload files"; route();
    } });
    const upBtn = h("button", { class: "violet", onclick: () => up.click() }, "Upload files");
    const imp = linkImporter(kind, () => { toast("Imported"); setTimeout(route, 1200); });
    v.append(h("div", { class: "panel", style: { marginBottom: "18px" } }, h("div", { class: "row", style: { alignItems: "flex-start" } }, upBtn, up, h("div", { style: { flex: 1, minWidth: "240px" } }, imp.el)),
      kind === "backgrounds" ? h("p", { class: "muted small", style: { marginBottom: 0 } }, "Tip: add a few long gameplay or satisfying clips here — story and text videos pick random segments from them.") : null));
  }
  let files = await loadFiles(kind, true);
  if (kind === "outputs") files = files.filter((f) => !/\.(srt)$/.test(f.ref));
  v.append(files.length ? h("div", { class: "gallery" }, files.map((f) => {
    const isVid = /\.(mp4|mov|mkv|webm|m4v|avi)$/i.test(f.ref);
    const isAud = /\.(mp3|wav|m4a|ogg|flac)$/i.test(f.ref);
    const m = h("div", { class: "media" + (kind === "outputs" ? "" : " wide") });
    if (isVid) m.append(h("video", { src: f.url, controls: true, preload: "none", poster: f.thumb }));
    else if (isAud) m.append(h("div", { style: { display: "grid", placeItems: "center", height: "100%", padding: "8px" } }, h("audio", { src: f.url, controls: true, preload: "none", style: { width: "100%" } })));
    else m.append(h("img", { class: "full", src: f.url }));
    return h("div", { class: "card" }, m, h("div", { class: "body" }, h("div", { class: "title", title: f.name }, f.name), h("div", { class: "meta" }, h("span", {}, fmtSize(f.size)), h("span", {}, new Date(f.mtime * 1000).toLocaleDateString())),
      h("div", { class: "btns" }, h("a", { href: f.url, download: "" }, h("button", { class: "sm" }, "Download")),
        h("button", { class: "sm ghost danger", onclick: async () => { if (confirm("Delete " + f.name + "?")) { await api.del(`/api/files?ref=${encodeURIComponent(f.ref)}`); route(); } } }, "Delete"))));
  })) : h("div", { class: "empty" }, "Nothing here yet."));
};

PAGES.calc = (v) => {
  v.append(h("h1", {}, "Creator Calculators"), h("p", { class: "lead" }, "Rough estimates for planning. Real payouts vary by niche, region and platform."));
  const mk = (title, inputs, compute) => {
    const els = inputs.map(([label, def]) => h("input", { type: "number", value: def, step: "any" }));
    const out = h("div", { class: "stat" }); const note = h("div", { class: "muted small" });
    const upd = () => { const [a, b] = compute(...els.map((e) => +e.value || 0)); out.textContent = a; note.textContent = b; };
    els.forEach((e) => (e.oninput = upd)); upd();
    return h("div", { class: "panel" }, h("h2", {}, title), inputs.map(([label], i) => field(label, els[i])), out, note);
  };
  const money = (x) => "$" + x.toLocaleString(undefined, { maximumFractionDigits: 2 });
  v.append(h("div", { class: "grid cols-3" },
    mk("Views → money", [["Views", 1000000], ["RPM ($ per 1,000 views)", 0.6]], (vw, rpm) => [money(vw / 1000 * rpm), "Shorts/TikTok RPM is typically $0.02–$1.00"]),
    mk("CPM ↔ RPM", [["CPM (advertiser $ / 1,000 impressions)", 8], ["Creator revenue share (%)", 55], ["Monetized views (%)", 60]], (cpm, share, mon) => [money(cpm * share / 100 * mon / 100) + " RPM", "RPM = CPM × share × monetized views"]),
    mk("Posts to a million views", [["Average views per post", 4000], ["Posts per day", 3], ["Goal views", 1000000]], (avg, ppd, goal) => {
      const posts = Math.ceil(goal / Math.max(1, avg)); return [posts.toLocaleString() + " posts", `≈ ${Math.ceil(posts / Math.max(1, ppd))} days at ${ppd}/day`]; }),
    mk("Clips from one video", [["Video length (min)", 90], ["Avg clip length (s)", 40], ["Usable content (%)", 35]], (len, clip, use) =>
      [Math.floor(len * 60 * use / 100 / Math.max(1, clip)) + " clips", "Only the strongest moments are worth posting"]),
    mk("Clipping campaign earnings", [["Views", 500000], ["Pay per 1,000 views ($)", 1.5], ["Max payout per clip ($)", 1000]], (vw, per, cap) => [money(Math.min(cap, vw / 1000 * per)), "Content-reward style campaigns"])));
};


PAGES.settings = async (v) => {
  v.append(h("h1", {}, "AI Settings"), h("p", { class: "lead" }, "Choose which AI does the thinking (picking viral moments, hook titles, descriptions, hashtags, writing scripts, fixing captions) and which engine transcribes speech. Keys stay on this computer in data/settings.json."));
  const data = await api.get("/api/settings");
  const st = data.settings;
  const L = st.llm, T = st.transcribe, F = st.features;
  const pw = (val, hint) => h("input", { type: "password", autocomplete: "off", placeholder: hint ? `saved (${hint}) — leave blank to keep` : "paste key", value: val || "" });

  // --- LLM provider ---
  let provider = L.provider;
  const cards = h("div", { class: "pcards" });
  const detail = h("div", { style: { marginTop: "16px" } });
  const ollamaSel = h("select", {}, h("option", { value: "" }, data.ollama_models.length ? "First installed model" : "No models installed"),
    data.ollama_models.map((m) => h("option", { value: m, selected: m === L.ollama_model }, m)));
  const cliModel = h("select", {}, [["sonnet", "Sonnet (recommended: fast + smart)"], ["opus", "Opus (smartest, uses limits faster)"], ["haiku", "Haiku (fastest)"]]
    .map(([a, b]) => h("option", { value: a, selected: a === L.claude_cli_model }, b)));
  const anthModel = h("select", {}, [["claude-opus-5-5", "Claude Opus 5.5 (best)"], ["claude-sonnet-5-5", "Claude Sonnet 5.5 (cheaper)"], ["claude-haiku-5-5", "Claude Haiku 5.5 (cheapest)"]]
    .map(([a, b]) => h("option", { value: a, selected: a === L.anthropic_model }, b)));
  const anthEffort = h("select", {}, ["low", "medium", "high", "xhigh"].map((e) => h("option", { value: e, selected: e === L.anthropic_effort }, e)));
  const anthKey = pw("", L.anthropic_api_key_hint);
  const oaBase = h("input", { type: "url", value: L.openai_base_url });
  const oaModel = h("input", { type: "text", value: L.openai_model, placeholder: "e.g. gpt-5.1, llama-3.3-70b-versatile, gemini-2.5-pro" });
  const oaKey = pw("", L.openai_api_key_hint);
  const presets = h("div", { class: "seg" }, [["OpenAI", "https://api.openai.com/v1"], ["Groq", "https://api.groq.com/openai/v1"], ["OpenRouter", "https://openrouter.ai/api/v1"],
    ["Gemini", "https://generativelanguage.googleapis.com/v1beta/openai"], ["LM Studio", "http://localhost:1234/v1"]].map(([n, u]) => h("button", { type: "button", onclick: () => (oaBase.value = u) }, n)));
  const PROV = {
    ollama: { title: "Local (Ollama)", tag: "Free · offline", desc: "Runs on your GPU. Private, but small models pick weaker moments.",
      body: () => [field("Model", ollamaSel, data.ollama_models.length ? "Bigger models (e.g. qwen2.5:7b) judge better if your VRAM allows." : "Install one: ollama pull qwen2.5:3b")] },
    claude_cli: { title: "Claude subscription", tag: "Pro / Max plan", desc: "Uses your Claude plan through the Claude Code CLI on this computer. Best picks at no extra cost.",
      body: () => [data.claude_cli ? h("p", { class: "ok small" }, "✓ Claude Code found at " + data.claude_cli) : h("p", { class: "err small" }, "Claude Code CLI not found. Install it and run `claude` once to log in with your subscription."),
        field("Model", cliModel),
        h("p", { class: "hint", style: { marginTop: "0" } }, "Each AI step is one message on your plan and counts toward its usage limits. Calls run as you, on this computer only.")] },
    anthropic: { title: "Anthropic API", tag: "Pay per use", desc: "Your own API key from platform.claude.com. Billed per token; a 1-hour podcast costs about $0.10–0.40 with Opus.",
      body: () => [h("div", { class: "row" }, field("Model", anthModel), field("Effort", anthEffort)), field("API key", anthKey, "Leave blank to use the ANTHROPIC_API_KEY environment variable.")] },
    openai_compat: { title: "Other API", tag: "OpenAI-compatible", desc: "OpenAI, Groq, OpenRouter, Gemini, LM Studio… any /chat/completions endpoint.",
      body: () => [field("Preset", presets), field("Base URL", oaBase), field("Model", oaModel), field("API key", oaKey)] },
  };
  const drawCards = () => {
    cards.replaceChildren(...Object.entries(PROV).map(([id, p]) => h("button", { type: "button", class: "pcard" + (provider === id ? " on" : ""), onclick: () => { provider = id; drawCards(); } },
      h("div", { class: "ptag" }, p.tag), h("div", { class: "ptitle" }, p.title), h("div", { class: "pdesc" }, p.desc))));
    detail.replaceChildren(...PROV[provider].body());
  };
  drawCards();

  // --- transcription ---
  let tprov = T.provider;
  const wSize = h("select", {}, data.whisper_sizes.map((z) => h("option", { value: z, selected: z === T.whisper_model },
    { tiny: "tiny (fastest, rough)", base: "base", small: "small (default, fast)", medium: "medium (more accurate)", "large-v3-turbo": "large-v3-turbo (best speed/accuracy on GPU)", "large-v3": "large-v3 (most accurate, slowest)" }[z] || z)));
  const tBase = h("input", { type: "url", value: T.api_base_url });
  const tModel = h("input", { type: "text", value: T.api_model });
  const tKey = pw("", T.api_key_hint);
  const tPresets = h("div", { class: "seg" }, [["Groq (free tier)", "https://api.groq.com/openai/v1", "whisper-large-v3"], ["OpenAI", "https://api.openai.com/v1", "whisper-1"]]
    .map(([n, u, m]) => h("button", { type: "button", onclick: () => { tBase.value = u; tModel.value = m; } }, n)));
  const tDetail = h("div");
  const tSeg = seg([["local", "Local Whisper (free, offline)"], ["openai_compat", "Cloud Whisper API"]], tprov, (x) => { tprov = x; drawT(); });
  const drawT = () => tDetail.replaceChildren(...(tprov === "local"
    ? [field("Model size", wSize, "Larger models fix names and numbers better. Models download automatically on first use.")]
    : [field("Preset", tPresets), field("Base URL", tBase), field("Model", tModel), field("API key", tKey, "Groq runs whisper-large-v3 very fast and has a free tier.")]));
  drawT();

  const cleanup = h("input", { type: "checkbox", checked: F.caption_cleanup });

  const collect = () => ({
    llm: { provider, ollama_model: ollamaSel.value, claude_cli_model: cliModel.value, anthropic_model: anthModel.value, anthropic_effort: anthEffort.value,
      anthropic_api_key: anthKey.value.trim(), openai_base_url: oaBase.value.trim(), openai_model: oaModel.value.trim(), openai_api_key: oaKey.value.trim() },
    transcribe: { provider: tprov, whisper_model: wSize.value, api_base_url: tBase.value.trim(), api_model: tModel.value.trim(), api_key: tKey.value.trim() },
    features: { caption_cleanup: cleanup.checked },
  });
  const save = async (quiet) => { await api.post("/api/settings", collect()); await refreshStatus(); if (!quiet) toast("Settings saved"); };
  const testBtn = (what, label) => {
    const b = h("button", { onclick: async () => {
      b.disabled = true; b.innerHTML = '<span class="spin"></span> Testing…';
      try { await save(true); const r = await api.post("/api/settings/test", { what });
        toast(what === "llm" ? `✓ ${r.provider} replied (${r.model})` : `✓ Speech-to-text ready (${typeof r.model === "string" ? r.model : r.model.size})`);
      } catch (e) { toast(e.message, true); }
      b.disabled = false; b.textContent = label;
    } }, label);
    return b;
  };
  v.append(
    h("div", { class: "panel", style: { marginBottom: "18px" } }, h("h2", {}, "AI model"), cards, detail,
      h("label", { class: "check", style: { marginTop: "6px" } }, cleanup, "Polish captions with AI (fixes misheard words, names and numbers before burning them in)"),
      h("div", { class: "btns", style: { marginTop: "16px" } }, h("button", { class: "primary", onclick: () => save().catch((e) => toast(e.message, true)) }, "Save"), testBtn("llm", "Test AI"))),
    h("div", { class: "panel" }, h("h2", {}, "Speech-to-text"), field("Engine", tSeg), tDetail,
      h("div", { class: "btns" }, h("button", { class: "primary", onclick: () => save().catch((e) => toast(e.message, true)) }, "Save"), testBtn("transcribe", "Test speech-to-text")),
      h("p", { class: "muted small" }, "Changing the engine re-transcribes videos the next time you analyze them.")));
};

// ---------- router ----------
function nav() {
  const cur = location.hash.slice(2).split("/")[0] || "home";
  $("#nav").replaceChildren(...ROUTES.map((r) => r.sec ? h("div", { class: "sec" }, r.sec) :
    h("a", { href: "#/" + r.id, class: cur === r.id ? "active" : "", html: icon(r.id) + `<span>${r.label}</span>` })));
}
async function route() {
  const [page, arg] = location.hash.slice(2).split("/");
  nav();
  const v = $("#view");
  v.replaceChildren();
  try { await (PAGES[page] || PAGES.home)(v, arg); } catch (e) { v.append(h("div", { class: "empty" }, "Error: " + e.message)); console.error(e); }
  window.scrollTo(0, 0);
}
async function refreshStatus() {
  try {
    S.status = await api.get("/api/status");
    const st = S.status;
    $("#sys").innerHTML = `<div><span class="dot"></span>Encoder <b>${st.encoder}</b></div>
      <div><span class="dot ${st.llm_model ? "" : "off"}"></span>AI <b>${st.llm_model || "not set"}</b> · ${st.llm_provider_label}</div>
      <div><span class="dot"></span>Whisper <b>${st.whisper.size}</b> · ${st.whisper.device}</div>`;
    if (st.vram) {
      const pct = Math.round(st.vram.used / st.vram.total * 100);
      $("#sys").append(h("div", { title: "GPU memory in use. Models are unloaded automatically when jobs finish." },
        h("span", { class: "dot" + (pct > 85 ? " off" : "") }), "VRAM ", h("b", {}, `${(st.vram.used / 1024).toFixed(1)}/${(st.vram.total / 1024).toFixed(1)} GB`), " ",
        h("a", { href: "#", style: { color: "var(--accent)" }, onclick: async (e) => {
          e.preventDefault();
          try { const r = await api.post("/api/gpu/release"); toast(`GPU freed: ${r.before?.used ?? "?"} → ${r.after?.used ?? "?"} MB`); } catch (err) { toast(err.message, true); }
          refreshStatus();
        } }, "free")));
    }
  } catch { $("#sys").textContent = "Server offline"; }
}

(async function init() {
  S.options = await api.get("/api/options");
  await refreshStatus();
  setInterval(refreshStatus, 30000);
  // re-attach to jobs still running (e.g. after a page reload)
  try { for (const j of await api.get("/api/jobs")) if (["queued", "running"].includes(j.status)) trackJob(j); } catch {}
  window.addEventListener("hashchange", route);
  route();
})();
