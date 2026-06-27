from html import escape

from .score import Recommendation

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bandcamp recommendations for {username}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 2rem auto;
          max-width: 760px; color: #222; }}
  h1 {{ font-size: 1.4rem; }}
  .rec {{ display: flex; gap: 1rem; padding: 1rem 0; border-top: 1px solid #eee; }}
  .rec img {{ width: 100px; height: 100px; object-fit: cover; background: #f3f3f3; }}
  .meta {{ flex: 1; }}
  .title {{ font-weight: 600; }}
  .artist {{ color: #555; }}
  .tags {{ color: #888; font-size: 0.85rem; margin-top: 0.25rem; }}
  .why {{ color: #777; font-size: 0.85rem; margin-top: 0.25rem; }}
  a {{ color: #1a6; text-decoration: none; }}
</style>
</head>
<body>
<h1>Recommendations for {username}</h1>
<p>{count} albums, ranked by how much taste their owners share with you.</p>
{rows}
</body>
</html>
"""

_ROW = """<div class="rec">
  {img}
  <div class="meta">
    <div class="title"><a href="{url}">{title}</a></div>
    <div class="artist">{artist}</div>
    <div class="tags">{tags}</div>
    <div class="why">{why}</div>
  </div>
</div>"""


def _row(rec: Recommendation) -> str:
    a = rec.album
    img = (f'<img src="{escape(a.art_url)}" alt="">' if a.art_url
           else '<div class="rec-noart"></div>')
    return _ROW.format(
        img=img,
        url=escape(a.url),
        title=escape(a.title),
        artist=escape(a.artist),
        tags=escape(", ".join(a.tags)),
        why=escape(rec.why),
    )


def render_html(recommendations: list[Recommendation], username: str) -> str:
    rows = "\n".join(_row(r) for r in recommendations)
    return _PAGE.format(username=escape(username),
                        count=len(recommendations), rows=rows)


def write_html(html: str, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
