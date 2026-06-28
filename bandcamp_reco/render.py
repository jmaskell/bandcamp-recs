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
  a { color: #1a6; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .reset { font-size: 0.8rem; }
</style>
</head>
<body>
<h1>Recommendations for __USERNAME_TEXT__</h1>
<p class="intro">Albums you don't own, ranked by how much taste their owners share with you.
Adjust the controls to re-rank instantly &mdash; <a href="#" class="reset" id="reset">reset</a>.</p>

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

<p class="count" id="count"></p>
<div id="recs"></div>
<noscript><p>This page needs JavaScript to rank and display the recommendations.</p></noscript>

<script>
const POOL = __POOL__;
const DEFAULTS = __DEFAULTS__;
const OWNED_SOURCES = new Set(__OWNED_SOURCES__);

const el = (id) => document.getElementById(id);
const controls = {
  cap: el("cap"), minf: el("minf"), src: el("src"), topn: el("topn"),
};
const hideOwned = el("hideOwned");

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
  const head = fans === 1 ? "1 fan who shares" : fans + " fans who each share";
  return "Owned by " + head + " ~" + typical + " " + albWord + " with your collection.";
}

function scored(cap) {
  return POOL.map((item) => {
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

function row(r, rank) {
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
  rows.sort((x, y) => (y.score - x.score) || (y.fans - x.fans));
  rows = diversify(rows, maxPer, topN);

  const container = el("recs");
  container.textContent = "";
  rows.forEach((r, i) => container.appendChild(row(r, i + 1)));

  el("count").textContent = rows.length + " of " + POOL.length +
    " candidate albums shown.";
}

for (const c of Object.values(controls)) c.addEventListener("input", render);
hideOwned.addEventListener("change", render);
el("reset").addEventListener("click", (e) => { e.preventDefault(); applyDefaults(); render(); });

applyDefaults();
render();
</script>
</body>
</html>
"""


def render_html(pool: list[dict], username: str, defaults: dict,
                owned_sources=()) -> str:
    """Render the interactive recommendations page. `pool` is the candidate
    data from score.candidate_pool; the page re-ranks it client-side from the
    control values, seeded by `defaults`. `owned_sources` is the set of
    labels/artists the user already owns, for the "hide owned" filter."""
    def embed(value) -> str:
        # JSON, made safe to sit inside a <script> tag (can't break out via </).
        return json.dumps(value).replace("</", "<\\/")

    return (
        _PAGE
        .replace("__POOL__", embed(pool))
        .replace("__DEFAULTS__", embed(defaults))
        .replace("__OWNED_SOURCES__", embed(sorted(owned_sources)))
        .replace("__USERNAME_TEXT__", _html_escape(username))
    )


def _html_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def write_html(html: str, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
