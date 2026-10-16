"""Scraper dan resolver stream untuk Rebahin (Tertiary / Indo Movie & Series Source Tatap).
Mendukung pencarian film/serial, parsing episode, dan decoding player JuicyCodes/HLS/MP4.
"""

import re
import json
import base64
import urllib.parse
from config import REBAHIN_BASE, HI_UA
from api.desync import _resolve_host

HEADERS = {
    "User-Agent": HI_UA,
    "Referer": REBAHIN_BASE + "/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

_rebahin_client = None

def _get_rebahin_client():
    global _rebahin_client
    if _rebahin_client is None:
        import httpx
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=60.0)
        _rebahin_client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(15.0, connect=6.0),
            limits=limits,
            headers=HEADERS,
            verify=False
        )
    return _rebahin_client


def _fetch(url: str, referer: str = None, timeout: int = 15) -> str:
    """Fetch helper menggunakan curl_cffi dengan CurlOpt.RESOLVE anti-ISP block, httpx fallback, dan desync fallback."""
    h = dict(HEADERS)
    if referer:
        h["Referer"] = referer

    p = urllib.parse.urlsplit(url)
    host = p.netloc.split(":")[0]

    # Resolve IP target anti-ISP DNS poison
    resolved_ip = _resolve_host(host)

    # 1. Coba curl_cffi dengan Chrome impersonation
    try:
        from curl_cffi import requests as creq
        from curl_cffi.curl import CurlOpt

        curl_opts = {}
        if resolved_ip and resolved_ip != host:
            port = p.port or 443
            curl_opts[CurlOpt.RESOLVE] = [f"{host}:{port}:{resolved_ip}"]

        r = creq.get(
            url,
            headers=h,
            impersonate="chrome124",
            timeout=timeout,
            allow_redirects=True,
            curl_options=curl_opts if curl_opts else None,
            verify=False
        )
        if r.status_code == 200:
            return r.text
    except Exception:
        pass

    # 2. Coba httpx
    try:
        client = _get_rebahin_client()
        r = client.get(url, headers=h)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass

    # 3. Fallback TLS Desync jika diblokir DPI
    try:
        from api.desync import tls_desync_request
        raw = tls_desync_request(url, headers=h, timeout=timeout)
        txt = raw.decode("utf-8", errors="replace")
        if txt and ("<html" in txt.lower() or "{" in txt or "var config" in txt):
            return txt
    except Exception:
        pass

    raise RuntimeError(f"Gagal memuat URL dari Rebahin: {url}")


def decode_juicycodes(payload: str) -> str:
    """Mendekripsi payload obfuscated JuicyCodes player ke Javascript config string."""
    sym_map = ['`', '%', '-', '+', '*', '$', '!', '_', '^', '=']
    sym_dict = {ch: str(i) for i, ch in enumerate(sym_map)}

    salt_str = payload[-3:]
    raw_body = payload[:-3]
    salt = int(''.join(str(ord(c) - 100) for c in salt_str))

    raw_body = raw_body.replace('_', '+').replace('-', '/')
    pad = len(raw_body) % 4
    if pad:
        raw_body += '=' * (4 - pad)
    b64 = base64.b64decode(raw_body).decode('latin1')

    digits = [sym_dict[c] for c in b64 if c in sym_dict]
    digit_str = ''.join(digits)

    chars = []
    for i in range(0, len(digit_str) - 3, 4):
        chunk = int(digit_str[i:i+4])
        code = (chunk % 1000) - salt
        chars.append(chr(code))
    return ''.join(chars)


def _is_title_match(query: str, target: str) -> bool:
    """Verifikasi apakah judul target cocok secara wajar dengan query pencarian."""
    def _sig(s: str) -> set:
        s = s.lower()
        s = re.sub(r'\b(sub\s*indo|subtitle\s*indonesia|film|anime|nonton|season\s*\d+|episode\s*\d+|s\d+|ep\s*\d+)\b', '', s)
        s = re.sub(r'[^a-z0-9\s]', ' ', s)
        tokens = [w for w in s.split() if len(w) > 1 and w not in ('the', 'a', 'an', 'no', 'of', 'and', 'di')]
        return set(tokens)

    sig_q = _sig(query)
    sig_t = _sig(target)
    if not sig_q or not sig_t:
        return True
    common = sig_q & sig_t
    overlap = len(common) / len(sig_q)
    return overlap >= 0.5


def search(query: str, limit: int = 10) -> list:
    """Cari film/serial di Rebahin. Return [{title, url, id, poster}]."""
    clean_q = re.sub(r"[^\w\s-]", "", query).strip()
    url = f"{REBAHIN_BASE}/?s={urllib.parse.quote_plus(clean_q)}"
    html = _fetch(url)

    pattern = re.compile(
        r'<div[^>]*class=[\'"][^\'"]*ml-item[^\'"]*[\'"][^>]*>.*?'
        r'<a[^>]*href=[\'"]([^\'"]+)[\'"][^>]*class=[\'"][^\'"]*ml-mask[^\'"]*[\'"][^>]*title=[\'"]([^\'"]+)[\'"].*?'
        r'<img[^>]*(?:data-original|src)=[\'"]([^\'"]+)[\'"]',
        re.S
    )
    results = []
    seen = set()
    for href, title, poster in pattern.findall(html):
        title = title.strip()
        slug = href.replace(REBAHIN_BASE, "").strip("/")
        if slug in seen:
            continue
        seen.add(slug)
        results.append({
            "title": title,
            "url": href,
            "id": f"rebahin:{slug}",
            "poster": poster,
        })
        if len(results) >= limit:
            break
    return results


def get_episodes(series_or_movie_url_or_slug: str) -> list:
    """Ambil daftar episode dari serial atau film Rebahin.
    Untuk movie mengembalikan 1 episode (Full Movie).
    Untuk series mengembalikan daftar episode 1..N.
    """
    if series_or_movie_url_or_slug.startswith("http"):
        url = series_or_movie_url_or_slug
    else:
        clean_slug = series_or_movie_url_or_slug.strip("/")
        url = f"{REBAHIN_BASE}/{clean_slug}"
        if not url.endswith("/"):
            url += "/"

    html = _fetch(url)

    # Temukan link watch/play
    watch_m = re.search(r'<div id="mv-info"[^>]*>.*?<a[^>]*href="([^"]+)"', html, re.S)
    watch_url = watch_m.group(1) if watch_m else (url.rstrip("/") + ("/watch" if "/series/" in url else "/play"))

    watch_html = _fetch(watch_url, referer=url)

    episodes_dict = {}
    # Jika TV Series: cek data-iframe pada tombol episode
    eps_raw = re.findall(r'<a[^>]*data-iframe="([^"]+)"[^>]*>(.*?)</a>', watch_html, re.S)
    for data_b64, label_raw in eps_raw:
        label = re.sub(r'<[^>]+>', '', label_raw).strip()
        num_m = re.search(r'\d+', label)
        ep_num = int(num_m.group(0)) if num_m else None
        if ep_num is None:
            continue
        try:
            iframe_url = base64.b64decode(data_b64).decode('utf-8', 'ignore')
        except Exception:
            iframe_url = data_b64

        if ep_num not in episodes_dict:
            episodes_dict[ep_num] = {
                "ep": ep_num,
                "title": f"Episode {ep_num}",
                "url": watch_url,
                "embed": iframe_url,
                "embeds": [iframe_url]
            }
        else:
            if iframe_url not in episodes_dict[ep_num]["embeds"]:
                episodes_dict[ep_num]["embeds"].append(iframe_url)
                # Prioritaskan JuicyCodes player jika ditemukan di server mirror
                if "/player/" in iframe_url:
                    episodes_dict[ep_num]["embed"] = iframe_url

    episodes = list(episodes_dict.values())

    # Jika Single Movie atau tidak ada multi-episode di #list-eps:
    if not episodes:
        servers_raw = re.findall(r'data-iframe="([^"]+)"', watch_html)
        if servers_raw:
            all_embeds = []
            for s in servers_raw:
                try:
                    dec = base64.b64decode(s).decode('utf-8', 'ignore')
                    if dec and dec not in all_embeds:
                        all_embeds.append(dec)
                except Exception:
                    if s not in all_embeds:
                        all_embeds.append(s)
            primary_embed = next((x for x in all_embeds if "/player/" in x), all_embeds[0] if all_embeds else "")
            episodes.append({
                "ep": 1,
                "title": "Full Movie",
                "url": watch_url,
                "embed": primary_embed,
                "embeds": all_embeds,
            })

    # Urutkan episode berdasarkan nomor episode
    episodes.sort(key=lambda x: x["ep"])
    return episodes


def _extract_stream_from_embed(embed_url: str, referer: str = None) -> dict:
    """Ekstrak stream HLS/MP4 langsung dari embed player Rebahin (JuicyCodes/Uservideo/Direct)."""
    hls_master = None
    variants = []
    subtitles = []

    if "/player/" in embed_url or "havanabrown" in embed_url or "juicy" in embed_url.lower():
        player_html = _fetch(embed_url, referer=referer or (REBAHIN_BASE + "/"))
        parts = re.findall(r'_juicycodes\((.*?)\);', player_html, re.S)
        if parts:
            full_str = ''.join(re.findall(r'["\']([^"\']*)["\']', parts[0]))
            decoded = decode_juicycodes(full_str)
            cfg_m = re.search(r'var config = ({.*?});', decoded)
            if cfg_m:
                cfg = json.loads(cfg_m.group(1))
                sources = cfg.get("sources", {})
                hls_master = sources.get("file")
                labels = sources.get("labels", {})
                for q_key, q_label in labels.items():
                    variants.append({"q": f"{q_key}p", "url": hls_master})
                if not variants and hls_master:
                    variants = [{"q": "720p", "url": hls_master}, {"q": "auto", "url": hls_master}]
                for tr in cfg.get("tracks", []):
                    if tr.get("kind") in ("captions", "subtitles"):
                        subtitles.append({
                            "lang": tr.get("language", "id"),
                            "label": tr.get("label", "Indonesian"),
                            "url": tr.get("file"),
                            "default": True
                        })

    if not hls_master and (embed_url.endswith(".mp4") or ".m3u8" in embed_url or "uservideo" in embed_url):
        hls_master = embed_url
        variants = [{"q": "auto", "url": hls_master}]

    if not hls_master:
        return None

    return {
        "master": hls_master,
        "variants": variants,
        "sub": subtitles[0]["url"] if subtitles else None,
        "sub_lang": "Indonesian (Sub Indo)",
        "referer": embed_url,
        "server": "Rebahin (Sub Indo)",
        "source": "rebahin",
        "tracks": subtitles,
        "subtitles": subtitles,
    }


def resolve_stream(title_or_slug: str, ep: int = 1) -> dict:
    """Selesaikan stream URL untuk judul/slug dan episode tertentu dari Rebahin."""
    episodes = []

    # 1. Coba ambil jika title_or_slug adalah URL atau slug langsung
    if "rebahin" in title_or_slug and ("http://" in title_or_slug or "https://" in title_or_slug):
        episodes = get_episodes(title_or_slug)
    else:
        if ("/" in title_or_slug or "-" in title_or_slug) and " " not in title_or_slug:
            try:
                episodes = get_episodes(title_or_slug)
            except Exception:
                pass

    # 2. Jika belum ditemukan, lakukan pencarian judul
    if not episodes:
        clean_q = re.sub(r'-[a-z0-9]{5,10}$', '', title_or_slug)
        clean_title = re.sub(r'-\d+$', '', clean_q).replace("-", " ").strip()
        search_res = search(clean_title)
        if not search_res and clean_title != title_or_slug:
            raw_title = re.sub(r'-\d+$', '', title_or_slug).replace("-", " ").strip()
            search_res = search(raw_title)

        if not search_res:
            simplified = re.sub(r'\b(?:season\s*\d+|\d+(?:nd|rd|th|st)\s*season|part\s*\d+|s\d+)\b', '', clean_title, flags=re.I).strip()
            if simplified and simplified != clean_title:
                search_res = search(simplified)

        if not search_res:
            raise RuntimeError(f"Judul '{title_or_slug}' tidak ditemukan di Rebahin")

        matched = None
        for cand in search_res:
            if _is_title_match(clean_title, cand.get("title", "")):
                matched = cand
                break
        if not matched:
            matched = search_res[0]

        episodes = get_episodes(matched["url"])

    if not episodes:
        raise RuntimeError("Tidak ada episode/video yang ditemukan di Rebahin")

    target_ep = next((e for e in episodes if e["ep"] == int(ep)), episodes[0])
    
    # 3. Ekstrak stream dari embed utama atau mirror lainnya
    embeds_to_try = target_ep.get("embeds") or [target_ep.get("embed", "")]
    for emb in embeds_to_try:
        if not emb:
            continue
        try:
            res = _extract_stream_from_embed(emb, referer=target_ep.get("url"))
            if res:
                return res
        except Exception:
            pass

    raise RuntimeError(f"Gagal mengekstrak stream video dari episode {ep} di Rebahin")


FALLBACK_GENRES = [
    {"slug": "action", "title": "Action"},
    {"slug": "adventure", "title": "Adventure"},
    {"slug": "animation", "title": "Anime / Animasi"},
    {"slug": "comedy", "title": "Comedy"},
    {"slug": "crime", "title": "Crime"},
    {"slug": "drama", "title": "Drama"},
    {"slug": "horror", "title": "Horror"},
    {"slug": "mystery", "title": "Mystery"},
    {"slug": "romance", "title": "Romance"},
    {"slug": "science-fiction", "title": "Sci-Fi"},
    {"slug": "thriller", "title": "Thriller"},
    {"slug": "war", "title": "War"},
    {"slug": "westseries", "title": "Barat (Series)"},
    {"slug": "drama-korea", "title": "Korea (Drakor)"},
    {"slug": "drama-china", "title": "Mandarin (Drachin)"},
    {"slug": "drama-jepang", "title": "Jepang"},
    {"slug": "thailand-series", "title": "Thailand"},
    {"slug": "series-indonesia", "title": "Indonesia"},
    {"slug": "populer", "title": "Populer"},
    {"slug": "rekomendasi-film", "title": "Rekomendasi Film"},
    {"slug": "adult", "title": "Adult / 18+"},
]


def scrape_genres() -> list:
    """Ambil list genre dari Rebahin. Return [{slug, title}]."""
    try:
        html = _fetch(REBAHIN_BASE + "/")
        raw_genres = re.findall(
            r'<a[^>]*href=[\"\'](?:https?://[^/\"\'\s]+)?/genre/([^/\"\'\s]+)/?[\"\'][^>]*>(.*?)</a>',
            html,
            re.I
        )
        out = []
        seen = set()
        for slug_raw, name_raw in raw_genres:
            slug = slug_raw.strip("/").lower()
            name = re.sub(r'<[^>]+>', '', name_raw).strip()
            name = name.replace("&#8211;", "-").replace("&amp;", "&")
            if not slug or not name or slug in seen:
                continue
            seen.add(slug)
            out.append({"slug": slug, "title": name})
        if out:
            return out
    except Exception:
        pass
    return list(FALLBACK_GENRES)


def browse_genre(genre_slug: str, page: int = 1) -> dict:
    """Ambil daftar film per genre dari Rebahin dengan pagination."""
    clean_slug = genre_slug.strip("/").lower()
    p = max(1, int(page or 1))
    url = f"{REBAHIN_BASE}/genre/{clean_slug}/page/{p}/" if p > 1 else f"{REBAHIN_BASE}/genre/{clean_slug}/"
    try:
        html = _fetch(url)
    except Exception:
        return {"items": [], "total_pages": 1, "page": p, "has_next": False, "genre": clean_slug, "source": "rebahin"}

    pattern = re.compile(
        r'<div[^>]*class=[\'\"][^\'\"]*ml-item[^\'\"]*[\'\"][^>]*>.*?'
        r'<a[^>]*href=[\'\"]([^\'\"]+)[\'\"][^>]*class=[\'\"][^\'\"]*ml-mask[^\'\"]*[\'\"][^>]*title=[\'\"]([^\'\"]+)[\'\"].*?'
        r'<img[^>]*(?:data-original|src)=[\'\"]([^\'\"]+)[\'\"]',
        re.S
    )
    items = []
    seen = set()
    for href, title, poster in pattern.findall(html):
        slug = href.replace(REBAHIN_BASE, "").strip("/")
        if slug in seen:
            continue
        seen.add(slug)
        clean_title = re.sub(r'&#\d+;', '', title).strip()
        items.append({
            "id": f"rebahin:{slug}",
            "slug": f"rebahin:{slug}",
            "title": clean_title,
            "poster": poster,
            "type": "Series" if ("series" in slug or "eps" in slug) else "Movie",
            "source": "rebahin",
        })

    pages = [int(x) for x in re.findall(rf'/genre/{re.escape(clean_slug)}/page/(\d+)/?', html)]
    total_pages = max(pages) if pages else (p + 1 if f"/page/{p+1}/" in html else p)
    return {
        "items": items,
        "page": p,
        "total_pages": total_pages,
        "has_next": p < total_pages,
        "genre": clean_slug,
        "source": "rebahin",
    }


def catalog(page: int = 1) -> dict:
    """Ambil katalog umum film/serial Rebahin terbaru."""
    p = max(1, int(page or 1))
    url = f"{REBAHIN_BASE}/page/{p}/" if p > 1 else f"{REBAHIN_BASE}/"
    try:
        html = _fetch(url)
    except Exception:
        return {"items": [], "total_pages": 1, "page": p, "has_next": False, "source": "rebahin"}

    pattern = re.compile(
        r'<div[^>]*class=[\'\"][^\'\"]*ml-item[^\'\"]*[\'\"][^>]*>.*?'
        r'<a[^>]*href=[\'\"]([^\'\"]+)[\'\"][^>]*class=[\'\"][^\'\"]*ml-mask[^\'\"]*[\'\"][^>]*title=[\'\"]([^\'\"]+)[\'\"].*?'
        r'<img[^>]*(?:data-original|src)=[\'\"]([^\'\"]+)[\'\"]',
        re.S
    )
    items = []
    seen = set()
    for href, title, poster in pattern.findall(html):
        slug = href.replace(REBAHIN_BASE, "").strip("/")
        if slug in seen:
            continue
        seen.add(slug)
        clean_title = re.sub(r'&#\d+;', '', title).strip()
        items.append({
            "id": f"rebahin:{slug}",
            "slug": f"rebahin:{slug}",
            "title": clean_title,
            "poster": poster,
            "type": "Series" if ("series" in slug or "eps" in slug) else "Movie",
            "source": "rebahin",
        })

    pages = [int(x) for x in re.findall(r'/page/(\d+)/?', html)]
    total_pages = max(pages) if pages else (p + 1 if f"/page/{p+1}/" in html else p)
    return {
        "items": items,
        "page": p,
        "total_pages": total_pages,
        "has_next": p < total_pages,
        "source": "rebahin",
    }

