"""Scraper dan resolver stream untuk Dutamovie21 (https://dutamovie21.now / https://aubergedelavenir.com).
Mendukung pencarian film/serial TV box office, katalog film terbaru, detail metadata,
dan multi-server embed player (Abyss, VOE, Callista/Minochinos, Luluvdo, HGCloud, dsb.)
dengan proteksi anti-DPI ISP menggunakan TLS Desync bypass.
"""

import os
import re
import urllib.parse
from config import HI_UA

DUTAMOVIE_BASE = os.getenv("DUTAMOVIE_BASE", "https://aubergedelavenir.com")
DUTAMOVIE_NOW = "https://dutamovie21.now"

HEADERS = {
    "User-Agent": HI_UA,
    "Referer": DUTAMOVIE_BASE + "/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

_dutamovie_client = None


def _get_client():
    global _dutamovie_client
    if _dutamovie_client is None:
        import httpx
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=60.0)
        _dutamovie_client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(15.0, connect=6.0),
            limits=limits,
            headers=HEADERS,
            verify=False
        )
    return _dutamovie_client


def _fetch(url: str, referer: str = None, timeout: int = 15) -> str:
    """Fetch helper dengan httpx, curl_cffi, dan fallback TLS desync jika diblokir ISP."""
    h = dict(HEADERS)
    if referer:
        h["Referer"] = referer

    # 1. Coba httpx direct
    try:
        client = _get_client()
        r = client.get(url, headers=h)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass

    # 2. Coba curl_cffi dengan Chrome impersonation
    try:
        from curl_cffi import requests as creq
        r = creq.get(
            url,
            headers=h,
            impersonate="chrome124",
            timeout=timeout,
            allow_redirects=True,
            verify=False
        )
        if r.status_code == 200:
            return r.text
    except Exception:
        pass

    # 3. Fallback TLS Desync jika diblokir DPI ISP
    try:
        from api.desync import tls_desync_request
        raw = tls_desync_request(url, headers=h, timeout=timeout)
        txt = raw.decode("utf-8", errors="replace")
        # Handle chunked transfer encoding jika ada
        if re.match(r'^[0-9a-fA-F]+\r\n', txt):
            parts = []
            rest = txt
            while rest:
                m = re.match(r'^([0-9a-fA-F]+)\r\n', rest)
                if not m:
                    parts.append(rest)
                    break
                csize = int(m.group(1), 16)
                if csize == 0:
                    break
                start = m.end()
                parts.append(rest[start:start+csize])
                rest = rest[start+csize+2:]
            txt = ''.join(parts)
        if txt and ("<html" in txt.lower() or "{" in txt):
            return txt
    except Exception:
        pass

    raise RuntimeError(f"Gagal memuat URL dari Dutamovie21: {url}")


def _parse_card(article_html: str) -> dict:
    """Parse kartu artikel film/serial dari Dutamovie21."""
    # Link & Title
    title_m = re.search(r'<h\d[^>]*class=[\"\'][^\"\']*entry-title[^\"\']*[\"\'][^>]*><a\s+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>', article_html, re.I)
    if not title_m:
        title_m = re.search(r'<a\s+href=[\"\']([^\"\']+)[\"\'][^>]*title=[\"\']([^\"\']+)[\"\']', article_html, re.I)
    if not title_m:
        title_m = re.search(r'<a\s+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>', article_html, re.I)
    if not title_m:
        return None

    href, raw_title = title_m.groups()
    title = re.sub(r'<[^>]+>', '', raw_title).replace("Permalink ke:", "").strip()

    # Slug
    p = urllib.parse.urlsplit(href)
    clean_path = p.path.strip("/")
    if not clean_path:
        return None
    is_series = clean_path.startswith("tv/")
    slug = f"dutamovie:{clean_path}"

    # Poster
    img_m = re.search(r'<img[^>]*src=[\"\']([^\"\']+)[\"\']', article_html)
    poster = img_m.group(1) if img_m else ""
    if poster.startswith("//"):
        poster = "https:" + poster

    # Rating
    rating_m = re.search(r'class=[\"\'](?:gmr-rating-content|rating|imdb)[^\"\']*[\"\']>([^<]+)', article_html, re.I)
    rating = rating_m.group(1).strip() if rating_m else ""

    # Year
    year_m = re.search(r'class=[\"\'](?:gmr-year|year|release)[^\"\']*[\"\']>.*?(\d{4})', article_html, re.S | re.I)
    year = year_m.group(1) if year_m else ""

    # Quality
    quality_m = re.search(r'class=[\"\'](?:gmr-quality-item|quality)[^\"\']*[\"\']>([^<]+)', article_html, re.I)
    quality = quality_m.group(1).strip() if quality_m else "HD"

    return {
        "id": slug,
        "slug": slug,
        "title": title,
        "poster": poster,
        "rating": rating,
        "year": year,
        "quality": quality,
        "type": "Series" if is_series else "Movie",
        "source": "dutamovie",
    }


def search(query: str, limit: int = 20) -> list:
    """Cari film/serial di Dutamovie21 berdasarkan kata kunci."""
    clean_q = (query or "").strip()
    if not clean_q:
        return []

    url = f"{DUTAMOVIE_BASE}/?s={urllib.parse.quote_plus(clean_q)}"
    try:
        html = _fetch(url)
    except Exception:
        return []

    results = []
    articles = re.findall(r'<article[^>]*id=[\"\']post-\d+[\"\'][^>]*>(.*?)</article>', html, re.S)
    for art in articles:
        item = _parse_card(art)
        if item:
            results.append(item)
            if len(results) >= limit:
                break
    return results


def catalog(page: int = 1) -> dict:
    """Ambil daftar film katalog terbaru dari Dutamovie21."""
    p = max(1, int(page))
    url = f"{DUTAMOVIE_BASE}/page/{p}/" if p > 1 else f"{DUTAMOVIE_BASE}/"
    try:
        html = _fetch(url)
    except Exception:
        return {"items": [], "total_pages": 1, "page": p, "has_next": False, "source": "dutamovie"}

    results = []
    articles = re.findall(r'<article[^>]*id=[\"\']post-\d+[\"\'][^>]*>(.*?)</article>', html, re.S)
    for art in articles:
        item = _parse_card(art)
        if item:
            results.append(item)

    # Deteksi pagination
    has_next = f"/page/{p+1}/" in html
    total_pages = p + (1 if has_next else 0)
    pages_m = re.findall(r'/page/(\d+)/', html)
    if pages_m:
        total_pages = max([int(x) for x in pages_m] + [total_pages])

    return {
        "items": results,
        "total_pages": total_pages,
        "page": p,
        "has_next": has_next,
        "source": "dutamovie",
    }


def get_detail(slug: str) -> dict:
    """Ambil detail informasi film atau serial TV dari Dutamovie21."""
    clean = slug
    if clean.startswith("dutamovie:"):
        clean = clean[len("dutamovie:"):]

    url = f"{DUTAMOVIE_BASE}/{clean}/"
    html = _fetch(url)

    # Judul
    t_m = re.search(r'<h1[^>]*class=[\"\'][^\"\']*entry-title[^\"\']*[\"\'][^>]*>(.*?)</h1>', html)
    title = re.sub(r'<[^>]+>', '', t_m.group(1)).replace("Nonton Film", "").replace("Nonton", "").strip() if t_m else clean

    # Poster
    img_m = re.search(r'<meta property=[\"\']og:image[\"\'] content=[\"\']([^\"\']+)[\"\']', html)
    poster = img_m.group(1) if img_m else ""

    # Sinopsis
    syn_m = re.search(r'<div class=[\"\'][^\"\']*(?:entry-content|gmr-movie-content)[^\"\']*[\"\'][^>]*>(.*?)</div>', html, re.S)
    synopsis = re.sub(r'<[^>]+>', '', syn_m.group(1)).strip() if syn_m else ""

    # Genres (ambil dari konten utama)
    genre_blocks = re.findall(r'<strong>Genre:\s*</strong>(.*?)(?:</div>|<strong>)', html, re.S | re.I)
    raw_genres = []
    if genre_blocks:
        raw_genres = re.findall(r'<a[^>]*>(.*?)</a>', genre_blocks[0])
    if not raw_genres:
        raw_genres = [g[1] for g in re.findall(r'<a\s+[^>]*href=[\"\'][^\"\']*/genre/([^/\"\'\?]+)/?[\"\'][^>]*>(.*?)</a>', html, re.I)]
    genres = list(dict.fromkeys([re.sub(r'<[^>]+>', '', x).strip() for x in raw_genres if x.strip()]))

    # Rating
    rating_m = re.search(r'itemprop=[\"\']ratingValue[\"\']>([^<]+)<', html)
    rating = rating_m.group(1).strip() if rating_m else ""

    # Tahun
    year_m = re.search(r'/year/(\d{4})/', html)
    year = year_m.group(1) if year_m else ""

    is_series = clean.startswith("tv/")

    return {
        "id": f"dutamovie:{clean}",
        "slug": f"dutamovie:{clean}",
        "title": title,
        "poster": poster,
        "synopsis": synopsis,
        "genres": genres,
        "rating": rating,
        "year": year,
        "type": "Series" if is_series else "Movie",
        "source": "dutamovie",
    }


def get_episodes(slug: str) -> list:
    """Ambil daftar episode untuk slug film/serial di Dutamovie21."""
    clean_slug = slug
    if clean_slug.startswith("dutamovie:"):
        clean_slug = clean_slug[len("dutamovie:"):]

    url = f"{DUTAMOVIE_BASE}/{clean_slug}/"
    html = _fetch(url)

    # Jika ini serial TV, cari link episode (/eps/...)
    links = re.findall(r'<a\s+[^>]*href=[\"\']([^\"\']*/eps/[^\"\']+)[\"\'][^>]*>(.*?)</a>', html, re.I)
    if links:
        episodes = []
        seen = set()
        for href, raw_text in links:
            if href in seen:
                continue
            seen.add(href)
            text = re.sub(r'<[^>]+>', '', raw_text).strip()
            num_m = re.search(r'(?:eps|episode)\s*(\d+)', text, re.I)
            if not num_m:
                num_m = re.search(r'episode-(\d+)', href, re.I)
            ep_num = int(num_m.group(1)) if num_m else (len(episodes) + 1)
            p = urllib.parse.urlsplit(href)
            ep_slug = p.path.strip("/")
            episodes.append({
                "ep": ep_num,
                "ep_id": str(ep_num),
                "title": text or f"Episode {ep_num}",
                "slug": f"dutamovie:{ep_slug}",
                "url": href,
            })
        episodes.sort(key=lambda x: x["ep"])
        if episodes:
            return episodes

    # Jika film biasa, kembalikan 1 episode
    return [{
        "ep": 1,
        "ep_id": "1",
        "title": "Full Movie",
        "slug": f"dutamovie:{clean_slug}",
        "url": url,
    }]


def resolve_stream(slug: str, ep: int = 1) -> dict:
    """Ambil semua server streaming untuk film/episode Dutamovie21."""
    clean_slug = slug
    if clean_slug.startswith("dutamovie:"):
        clean_slug = clean_slug[len("dutamovie:"):]

    # Cek apakah ini serial tv dan butuh URL episode spesifik
    target_url = f"{DUTAMOVIE_BASE}/{clean_slug}/"
    if clean_slug.startswith("tv/"):
        eps = get_episodes(clean_slug)
        target = next((x for x in eps if x["ep"] == int(ep)), None)
        if target and target.get("url"):
            target_url = target["url"]

    html = _fetch(target_url)

    # 1. Cari iframe utama di halaman ini
    iframes = re.findall(r'<iframe[^>]*src=[\"\']([^\"\']+)[\"\']', html, re.I)
    main_iframe = iframes[0] if iframes else None

    # 2. Cari semua link server player tambahan (?player=2, ?player=3, dst.)
    server_links = re.findall(r'<a\s+[^>]*href=[\"\']([^\"\']*(?:\?player=\d+|/[^/\"\']*/\?player=\d+))[\"\'][^>]*>(.*?)</a>', html, re.I)

    servers = []
    seen_urls = set()

    def _server_name(embed_url: str, idx: int, orig_label: str = "") -> str:
        domain = urllib.parse.urlsplit(embed_url).netloc.lower()
        if "abyss" in domain:
            label = "Abyss Player (Fast)"
        elif "voe" in domain:
            label = "VOE Stream"
        elif "callistanise" in domain or "minochinos" in domain:
            label = "Minochinos / Callista"
        elif "luluvdo" in domain or "luluvid" in domain:
            label = "Luluvid Stream"
        elif "veev" in domain:
            label = "Veev Player"
        elif "hgcloud" in domain:
            label = "HGCloud"
        elif "p2p" in domain:
            label = "P2P Stream"
        elif "embedpyrox" in domain:
            label = "Pyrox Player"
        else:
            clean_dom = domain.replace("www.", "").split(".")[0].capitalize()
            label = f"{clean_dom} Player" if clean_dom else f"Server {idx}"
        return f"Server {idx}: {label}"

    if main_iframe:
        seen_urls.add(main_iframe)
        s_name = _server_name(main_iframe, 1, "Server 1")
        servers.append({
            "name": s_name,
            "url": main_iframe,
            "is_embed": True,
            "is_m3u8": False
        })

    # Ambil iframe dari tab server lainnya (max 5 server tambahan untuk efisiensi respon)
    idx = 2
    for s_href, s_lbl in server_links[:6]:
        full_s_url = urllib.parse.urljoin(target_url, s_href)
        try:
            s_html = _fetch(full_s_url, referer=target_url, timeout=5)
            s_iframes = re.findall(r'<iframe[^>]*src=[\"\']([^\"\']+)[\"\']', s_html, re.I)
            if s_iframes:
                s_emb = s_iframes[0]
                if s_emb not in seen_urls:
                    seen_urls.add(s_emb)
                    s_name = _server_name(s_emb, idx, s_lbl)
                    servers.append({
                        "name": s_name,
                        "url": s_emb,
                        "is_embed": True,
                        "is_m3u8": False
                    })
                    idx += 1
        except Exception:
            continue

    if not servers:
        raise RuntimeError("Tidak ada link player stream yang ditemukan di Dutamovie21")

    # Pilih server default yang paling stabil (misalnya Abyss Player atau server non-Pyrox)
    primary = servers[0]
    for s in servers:
        if "embedpyrox" not in s["url"]:
            primary = s
            break

    variants = []
    for s in servers:
        variants.append({
            "q": s["name"],
            "url": s["url"],
            "is_embed": True,
            "is_m3u8": False
        })

    return {
        "master": primary["url"],
        "url": primary["url"],
        "is_embed": True,
        "is_m3u8": False,
        "embed_url": primary["url"],
        "variants": variants,
        "subtitles": [],
        "servers": servers,
        "source": "dutamovie",
    }


FALLBACK_GENRES = [
    {"slug": "action", "title": "Action"},
    {"slug": "adventure", "title": "Adventure"},
    {"slug": "animasi", "title": "Animasi / Anime"},
    {"slug": "comedy", "title": "Comedy"},
    {"slug": "crime", "title": "Crime"},
    {"slug": "drama", "title": "Drama"},
    {"slug": "fantasy", "title": "Fantasy"},
    {"slug": "horror", "title": "Horror"},
    {"slug": "mystery", "title": "Mystery"},
    {"slug": "romance", "title": "Romance"},
    {"slug": "science-fiction", "title": "Science Fiction"},
    {"slug": "thriller", "title": "Thriller"},
    {"slug": "box-office", "title": "Box Office"},
    {"slug": "serial-tv-terbaru", "title": "Serial TV"},
]


def scrape_genres() -> list:
    """Ambil list genre dari menu Dutamovie21. Return [{slug, title}]."""
    try:
        html = _fetch(DUTAMOVIE_BASE + "/")
        m = re.search(r'<span>Genre</span></span></a>\s*<ul class=[\"\']sub-menu[\"\']>(.*?)</ul>', html, re.S)
        out = []
        seen = set()
        if m:
            links = re.findall(r'<a[^>]*href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>', m.group(1))
            for href, text in links:
                title = re.sub(r'<[^>]+>', '', text).strip()
                slug = href.strip("/").split("/")[-1].lower()
                if not slug or not title or slug in seen:
                    continue
                seen.add(slug)
                out.append({"slug": slug, "title": title})
        if out:
            return out
    except Exception:
        pass
    return list(FALLBACK_GENRES)


def browse_genre(genre_slug: str, page: int = 1) -> dict:
    """Ambil daftar film per genre/kategori dari Dutamovie21 dengan pagination."""
    clean_slug = genre_slug.strip("/").lower()
    p = max(1, int(page or 1))
    url = f"{DUTAMOVIE_BASE}/{clean_slug}/page/{p}/" if p > 1 else f"{DUTAMOVIE_BASE}/{clean_slug}/"
    try:
        html = _fetch(url)
    except Exception:
        return {"items": [], "total_pages": 1, "page": p, "has_next": False, "genre": clean_slug, "source": "dutamovie"}

    results = []
    articles = re.findall(r'<article[^>]*id=[\"\']post-\d+[\"\'][^>]*>(.*?)</article>', html, re.S)
    for art in articles:
        item = _parse_card(art)
        if item:
            results.append(item)

    has_next = f"/page/{p+1}/" in html
    total_pages = p + (1 if has_next else 0)
    pages_m = re.findall(rf'/{re.escape(clean_slug)}/page/(\d+)/', html)
    if not pages_m:
        pages_m = re.findall(r'/page/(\d+)/', html)
    if pages_m:
        total_pages = max([int(x) for x in pages_m] + [total_pages])

    return {
        "items": results,
        "total_pages": total_pages,
        "page": p,
        "has_next": has_next,
        "genre": clean_slug,
        "source": "dutamovie",
    }

