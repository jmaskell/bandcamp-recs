import json

_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bandcamp recommendations for __USERNAME_TEXT__</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; margin: 2rem auto;
         max-width: 820px; color: #222; padding: 0 1rem; }
  h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
  .intro { color: #666; margin-top: 0; }
  .controls { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.75rem 1.5rem;
              background: #fafafa; border: 1px solid #eee; border-radius: 8px;
              padding: 1rem 1.25rem; margin: 1rem 0; }
  .ctrl label { display: block; font-size: 0.8rem; color: #444; font-weight: 600;
                margin-bottom: 0.2rem; }
  .ctrl input[type=range] { width: 100%; }
  .ctrl .val { font-weight: 700; color: #1a6; }
  .ctrl .hint { font-size: 0.72rem; color: #999; }
  .toggle { display: block; margin: 0.75rem 0 0; font-size: 0.9rem; color: #333;
            cursor: pointer; }
  .toggle input { margin-right: 0.4rem; }
  .toggle .hint { color: #999; font-size: 0.8rem; }
  .count { color: #666; font-size: 0.9rem; margin: 0.5rem 0 0; }
  .rec { display: flex; gap: 1rem; padding: 1rem 0; border-top: 1px solid #eee; }
  .rec img { width: 100px; height: 100px; object-fit: cover; background: #f3f3f3; flex: none; }
  .rec .noart { width: 100px; height: 100px; background: #f3f3f3; flex: none; }
  .meta { flex: 1; min-width: 0; }
  .rank { color: #bbb; font-weight: 700; margin-right: 0.4rem; }
  .title { font-weight: 600; }
  .artist { color: #555; }
  .tags { color: #888; font-size: 0.85rem; margin-top: 0.25rem; }
  .why { color: #777; font-size: 0.85rem; margin-top: 0.25rem; }
  .apple { font-size: 0.8rem; margin-top: 0.25rem; }
  .apple a { color: #fa2d6c; }
  .apple .na { color: #bbb; }
  .flag { background: none; border: none; cursor: pointer; color: #bbb;
          font-size: 0.85rem; padding: 0; margin-left: 0.5rem; }
  .flag.on { color: #fa2d6c; }
  a { color: #1a6; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .reset { font-size: 0.8rem; }
  .viewtabs { display: flex; gap: 0.5rem; margin: 1rem 0 0.5rem; }
  .tab { background: #f3f3f3; border: 1px solid #e2e2e2; border-radius: 999px;
         padding: 0.3rem 0.9rem; font: inherit; font-size: 0.85rem; color: #555; cursor: pointer; }
  .tab.on { background: #1a6; border-color: #1a6; color: #fff; }
  #recordSearch { width: 100%; box-sizing: border-box; padding: 0.5rem 0.7rem;
                  border: 1px solid #ddd; border-radius: 8px; font: inherit; margin: 0.5rem 0; }
  .rec.pick { cursor: pointer; }
  .rec.pick:hover { background: #fafafa; }
  #recordHeader { display: flex; gap: 1rem; align-items: center; margin: 1rem 0;
                  padding: 0.75rem; background: #fafafa; border: 1px solid #eee; border-radius: 8px; }
  #recordHeader img, #recordHeader .noart { width: 64px; height: 64px; }
  .simlabel { color: #999; font-size: 0.75rem; }
</style>
</head>
<body>
<h1>Recommendations for __USERNAME_TEXT__</h1>
<p class="intro">Albums you don't own, ranked by how much taste their owners share with you.
Adjust the controls to re-rank instantly &mdash; <a href="#" class="reset" id="reset">reset</a>.</p>

<div class="viewtabs" id="viewtabs" style="display:none">
  <button class="tab on" id="tabAll" type="button">Whole collection</button>
  <button class="tab" id="tabRecord" type="button">By record</button>
</div>
<div id="recordPicker" style="display:none">
  <input type="text" id="recordSearch" placeholder="Search your collection&hellip;" autocomplete="off">
  <p class="count" id="pickerCount"></p>
  <div id="recordList"></div>
</div>
<div id="recordHeader" style="display:none"></div>
<div id="results">

<div class="controls">
  <div class="ctrl">
    <label>Affinity cap: <span class="val" id="capVal"></span></label>
    <input type="range" id="cap" min="1" max="15" step="1">
    <div class="hint">How much a single fan can count. Lower = favour broad consensus; higher = favour deep, high-overlap picks.</div>
  </div>
  <div class="ctrl">
    <label>Minimum fans: <span class="val" id="minfVal"></span></label>
    <input type="range" id="minf" min="2" max="30" step="1">
    <div class="hint">Only show albums owned by at least this many of your taste-neighbours.</div>
  </div>
  <div class="ctrl">
    <label>Max per label/artist: <span class="val" id="srcVal"></span></label>
    <input type="range" id="src" min="1" max="8" step="1">
    <div class="hint">Stops one label or artist from flooding the list.</div>
  </div>
  <div class="ctrl">
    <label>Show top: <span class="val" id="topnVal"></span></label>
    <input type="range" id="topn" min="10" max="100" step="5">
    <div class="hint">How many recommendations to display.</div>
  </div>
</div>

<label class="toggle"><input type="checkbox" id="hideOwned"> Hide labels/artists I already
own music from <span class="hint" id="ownedCount"></span></label>
<div id="appleControls" style="display:none">
  <label class="toggle"><input type="checkbox" id="hideOnApple"> Hide albums on Apple Music</label>
  <label class="toggle"><input type="checkbox" id="hideNotApple"> Hide albums not on Apple Music</label>
</div>

<p class="count" id="count"></p>
<div id="flagBar" style="display:none; font-size:0.85rem; color:#666; margin:0.5rem 0;">
  <span id="flagCount">0 flagged</span>
  &mdash; <a href="#" id="flagExport">Export</a>
  &middot; <a href="#" id="flagClear">Clear</a>
</div>
<div id="recs"></div>
</div>
<noscript><p>This page needs JavaScript to rank and display the recommendations.</p></noscript>

<script>
const POOL = __POOL__;
const DEFAULTS = __DEFAULTS__;
const OWNED_SOURCES = new Set(__OWNED_SOURCES__);
const APPLE_ENABLED = __APPLE_ENABLED__;
const OWNED_RECORDS = __OWNED_RECORDS__;
const ALBUMS = __ALBUMS__;
const BYRECORD = __BYRECORD__;

let CURRENT = POOL;     // the pool the engine currently ranks
let mode = "all";       // "all" | "record"
let selectedKey = null; // selected owned-record key in "by record" mode

function poolForRecord(key) {
  return (BYRECORD[key] || []).map((ref) => {
    const meta = ALBUMS[ref.a] || {};
    return Object.assign({}, meta, { hist: ref.h, fans: ref.f });
  });
}

function applyMode() {
  const recordMode = mode === "record";
  el("recordPicker").style.display = (recordMode && !selectedKey) ? "" : "none";
  el("recordHeader").style.display = (recordMode && selectedKey) ? "" : "none";
  el("results").style.display = (recordMode && !selectedKey) ? "none" : "";
  el("tabAll").className = "tab" + (recordMode ? "" : " on");
  el("tabRecord").className = "tab" + (recordMode ? " on" : "");
}

function renderRecordHeader(r) {
  const h = el("recordHeader");
  h.textContent = "";
  if (r.art) {
    const img = document.createElement("img");
    img.src = r.art; img.alt = ""; img.loading = "lazy";
    h.appendChild(img);
  } else {
    const ph = document.createElement("div"); ph.className = "noart"; h.appendChild(ph);
  }
  const meta = document.createElement("div"); meta.className = "meta";
  const lab = document.createElement("div"); lab.className = "simlabel"; lab.textContent = "Similar to";
  const title = document.createElement("div"); title.className = "title";
  const a = document.createElement("a");
  a.href = r.url; a.textContent = r.title; a.target = "_blank"; a.rel = "noopener";
  title.appendChild(a);
  const artist = document.createElement("div"); artist.className = "artist"; artist.textContent = r.artist;
  const back = document.createElement("a");
  back.href = "#"; back.className = "reset"; back.textContent = "← back to my records";
  back.addEventListener("click", (e) => { e.preventDefault(); selectedKey = null; applyMode(); });
  meta.appendChild(lab); meta.appendChild(title); meta.appendChild(artist); meta.appendChild(back);
  h.appendChild(meta);
}

function renderPicker() {
  const q = el("recordSearch").value.trim().toLowerCase();
  const matches = OWNED_RECORDS.filter((r) =>
    !q || r.title.toLowerCase().includes(q) || r.artist.toLowerCase().includes(q));
  el("pickerCount").textContent =
    OWNED_RECORDS.length + " of your records have enough data" +
    (q ? " · " + matches.length + " match" : "");
  const list = el("recordList");
  list.textContent = "";
  for (const r of matches) {
    const wrap = document.createElement("div");
    wrap.className = "rec pick";
    if (r.art) {
      const img = document.createElement("img");
      img.src = r.art; img.alt = ""; img.loading = "lazy";
      wrap.appendChild(img);
    } else {
      const ph = document.createElement("div"); ph.className = "noart"; wrap.appendChild(ph);
    }
    const meta = document.createElement("div"); meta.className = "meta";
    const t = document.createElement("div"); t.className = "title"; t.textContent = r.title;
    const ar = document.createElement("div"); ar.className = "artist"; ar.textContent = r.artist;
    meta.appendChild(t); meta.appendChild(ar);
    wrap.appendChild(meta);
    wrap.addEventListener("click", () => selectRecord(r.key));
    list.appendChild(wrap);
  }
}

function selectRecord(key) {
  selectedKey = key;
  CURRENT = poolForRecord(key);
  const r = OWNED_RECORDS.find((x) => x.key === key);
  if (r) renderRecordHeader(r);
  applyMode();
  render();
}
const el = (id) => document.getElementById(id);
const controls = {
  cap: el("cap"), minf: el("minf"), src: el("src"), topn: el("topn"),
};
const hideOwned = el("hideOwned");

const FLAG_KEY = "bandcampAppleFlags";

function loadFlags() {
  try { return JSON.parse(localStorage.getItem(FLAG_KEY)) || {}; }
  catch (e) { return {}; }
}
function saveFlags(flags) {
  localStorage.setItem(FLAG_KEY, JSON.stringify(flags));
}
function updateFlagCount() {
  const n = Object.keys(loadFlags()).length;
  el("flagCount").textContent = n + " flagged";
}
function toggleFlag(item) {
  const flags = loadFlags();
  if (flags[item.url]) {
    delete flags[item.url];
  } else {
    flags[item.url] = {
      title: item.title, artist: item.artist, url: item.url,
      apple: item.apple || "unknown", appleUrl: item.appleUrl || "",
      appleName: item.appleName || "", appleArtist: item.appleArtist || "",
    };
  }
  saveFlags(flags);
  updateFlagCount();
  return !!flags[item.url];
}

function applyDefaults() {
  controls.cap.value = DEFAULTS.affinity_cap;
  controls.minf.value = DEFAULTS.min_fans;
  controls.src.value = DEFAULTS.max_per_source;
  controls.topn.value = DEFAULTS.top_n;
  hideOwned.checked = DEFAULTS.hide_owned_sources;
  el("ownedCount").textContent =
    "(" + OWNED_SOURCES.size + " in your collection)";
}

function whyText(fans, typical) {
  const albWord = typical === 1 ? "album" : "albums";
  const who = mode === "record" ? " of this record" : "";
  const head = fans === 1 ? "1 fan" + who + " who shares"
                          : fans + " fans" + who + " who each share";
  return "Owned by " + head + " ~" + typical + " " + albWord + " with your collection.";
}

function scored(cap) {
  return CURRENT.map((item) => {
    let score = 0, fans = 0, sumShared = 0;
    for (const aff in item.hist) {
      const a = +aff, cnt = item.hist[aff];
      score += cnt * Math.min(a, cap);
      fans += cnt;
      sumShared += a * cnt;
    }
    return { item, score, fans, typical: Math.round(sumShared / fans) };
  });
}

function diversify(rows, maxPer, topN) {
  const selected = [], deferred = [], per = {};
  for (const r of rows) {
    if (selected.length >= topN) break;
    const c = per[r.item.source] || 0;
    if (c < maxPer) { selected.push(r); per[r.item.source] = c + 1; }
    else deferred.push(r);
  }
  for (const r of deferred) {
    if (selected.length >= topN) break;
    selected.push(r);
  }
  return selected;
}

function row(r, rank, flags) {
  const it = r.item;
  const wrap = document.createElement("div");
  wrap.className = "rec";

  if (it.art) {
    const img = document.createElement("img");
    img.src = it.art; img.alt = ""; img.loading = "lazy";
    wrap.appendChild(img);
  } else {
    const ph = document.createElement("div");
    ph.className = "noart";
    wrap.appendChild(ph);
  }

  const meta = document.createElement("div");
  meta.className = "meta";

  const title = document.createElement("div");
  title.className = "title";
  const num = document.createElement("span");
  num.className = "rank"; num.textContent = rank + ".";
  const a = document.createElement("a");
  a.href = it.url; a.textContent = it.title; a.target = "_blank"; a.rel = "noopener";
  title.appendChild(num); title.appendChild(a);

  const artist = document.createElement("div");
  artist.className = "artist"; artist.textContent = it.artist;

  meta.appendChild(title);
  meta.appendChild(artist);

  if (it.tags && it.tags.length) {
    const tags = document.createElement("div");
    tags.className = "tags"; tags.textContent = it.tags.join(", ");
    meta.appendChild(tags);
  }

  const why = document.createElement("div");
  why.className = "why"; why.textContent = whyText(r.fans, r.typical);
  meta.appendChild(why);

  if (APPLE_ENABLED) {
    const apple = document.createElement("div");
    apple.className = "apple";
    if (it.apple === "available" && it.appleUrl) {
      const al = document.createElement("a");
      al.href = it.appleUrl; al.textContent = "Apple Music";
      al.target = "_blank"; al.rel = "noopener";
      apple.appendChild(al);
    } else {
      const na = document.createElement("span");
      na.className = "na"; na.textContent = "Not on Apple Music";
      apple.appendChild(na);
    }
    const flagged = !!flags[it.url];
    const fb = document.createElement("button");
    fb.className = "flag" + (flagged ? " on" : "");
    fb.textContent = flagged ? "⚑ flagged" : "⚐ flag";
    fb.title = "Flag a wrong Apple Music match";
    fb.addEventListener("click", () => {
      const on = toggleFlag(it);
      fb.className = "flag" + (on ? " on" : "");
      fb.textContent = on ? "⚑ flagged" : "⚐ flag";
    });
    apple.appendChild(fb);
    meta.appendChild(apple);
  }

  wrap.appendChild(meta);
  return wrap;
}

function render() {
  const cap = +controls.cap.value;
  const minf = +controls.minf.value;
  const maxPer = +controls.src.value;
  const topN = +controls.topn.value;

  el("capVal").textContent = cap;
  el("minfVal").textContent = minf;
  el("srcVal").textContent = maxPer;
  el("topnVal").textContent = topN;

  let rows = scored(cap).filter((r) => r.fans >= minf);
  if (hideOwned.checked) {
    rows = rows.filter((r) => !OWNED_SOURCES.has(r.item.source));
  }
  if (APPLE_ENABLED) {
    if (el("hideOnApple").checked) {
      rows = rows.filter((r) => r.item.apple !== "available");
    }
    if (el("hideNotApple").checked) {
      rows = rows.filter((r) => r.item.apple === "available");
    }
  }
  rows.sort((x, y) => (y.score - x.score) || (y.fans - x.fans));
  rows = diversify(rows, maxPer, topN);

  const container = el("recs");
  container.textContent = "";
  const flags = APPLE_ENABLED ? loadFlags() : {};
  rows.forEach((r, i) => container.appendChild(row(r, i + 1, flags)));

  el("count").textContent = rows.length + " of " + CURRENT.length +
    " candidate albums shown.";
}

for (const c of Object.values(controls)) c.addEventListener("input", render);
hideOwned.addEventListener("change", render);
if (APPLE_ENABLED) {
  el("appleControls").style.display = "";
  el("hideOnApple").addEventListener("change", render);
  el("hideNotApple").addEventListener("change", render);
  el("flagBar").style.display = "";
  updateFlagCount();
  el("flagExport").addEventListener("click", (e) => {
    e.preventDefault();
    const data = JSON.stringify(Object.values(loadFlags()), null, 2);
    const blob = new Blob([data], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "apple-music-flags.json";
    a.click();
    URL.revokeObjectURL(a.href);
  });
  el("flagClear").addEventListener("click", (e) => {
    e.preventDefault();
    localStorage.removeItem(FLAG_KEY);
    updateFlagCount();
    render();
  });
}
el("reset").addEventListener("click", (e) => {
  e.preventDefault();
  applyDefaults();
  if (APPLE_ENABLED) { el("hideOnApple").checked = false; el("hideNotApple").checked = false; }
  render();
});

if (OWNED_RECORDS.length) {
  el("viewtabs").style.display = "";
  el("tabAll").addEventListener("click", () => {
    mode = "all"; selectedKey = null; CURRENT = POOL; applyMode(); render();
  });
  el("tabRecord").addEventListener("click", () => {
    mode = "record"; renderPicker(); applyMode();
  });
  el("recordSearch").addEventListener("input", renderPicker);
}

applyDefaults();
render();
</script>
</body>
</html>
"""


def render_html(pool: list[dict], username: str, defaults: dict,
                owned_sources=(), apple_enabled: bool = False,
                owned_records=(), albums=None, by_record=None) -> str:
    """Render the interactive recommendations page. `pool` is the candidate
    data from score.candidate_pool; the page re-ranks it client-side from the
    control values, seeded by `defaults`. `owned_sources` is the set of
    labels/artists the user already owns, for the "hide owned" filter.

    `owned_records`, `albums`, and `by_record` power the "By record" view:
    the user's pickable records, a deduped album-metadata table, and per-record
    references into it. Omit them and the per-record UI stays hidden."""
    def embed(value) -> str:
        # JSON, made safe to sit inside a <script> tag (can't break out via </).
        return json.dumps(value).replace("</", "<\\/")

    return (
        _PAGE
        .replace("__POOL__", embed(pool))
        .replace("__DEFAULTS__", embed(defaults))
        .replace("__OWNED_SOURCES__", embed(sorted(owned_sources)))
        .replace("__OWNED_RECORDS__", embed(list(owned_records)))
        .replace("__ALBUMS__", embed(albums or {}))
        .replace("__BYRECORD__", embed(by_record or {}))
        .replace("__USERNAME_TEXT__", _html_escape(username))
        .replace("__APPLE_ENABLED__", "true" if apple_enabled else "false")
    )


def _html_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def write_html(html: str, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
