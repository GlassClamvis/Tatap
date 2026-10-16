"""API Module untuk Pencarian, Katalog, dan Stream Film Non-Anime & Serial TV."""
import re
import urllib.parse
import httpx

CINEMETA_SEARCH_MOVIE = "https://v3-cinemeta.strem.io/catalog/movie/top/search={}.json"
CINEMETA_SEARCH_SERIES = "https://v3-cinemeta.strem.io/catalog/series/top/search={}.json"
CINEMETA_CATALOG_MOVIE = "https://v3-cinemeta.strem.io/catalog/movie/top/skip={}.json"
CINEMETA_CATALOG_SERIES = "https://v3-cinemeta.strem.io/catalog/series/top/skip={}.json"
CINEMETA_DETAIL_MOVIE = "https://v3-cinemeta.strem.io/meta/movie/{}.json"
CINEMETA_DETAIL_SERIES = "https://v3-cinemeta.strem.io/meta/series/{}.json"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
_client = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=60.0)
        _client = httpx.Client(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=limits,
            headers={"User-Agent": _UA},
            follow_redirects=True,
            verify=False
        )
    return _client


def _fetch_json(url: str) -> dict:
    try:
        c = _get_client()
        r = c.get(url)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _clean_imdb(raw_id: str) -> str:
    m = re.search(r"(tt\d+)", str(raw_id or ""))
    return m.group(1) if m else str(raw_id or "").strip()


def search_movies(query: str, limit: int = 25, media_type: str = "all") -> list:
    """Cari film & serial TV via katalog global Cinemeta (IMDb/TMDB)."""
    q_clean = (query or "").strip()
    if not q_clean:
        return []
    q_enc = urllib.parse.quote(q_clean)
    results = []
    seen = set()

    types_to_fetch = []
    if media_type in ("all", "movie"):
        types_to_fetch.append(("movie", CINEMETA_SEARCH_MOVIE.format(q_enc)))
    if media_type in ("all", "series"):
        types_to_fetch.append(("series", CINEMETA_SEARCH_SERIES.format(q_enc)))

    for m_type, url in types_to_fetch:
        data = _fetch_json(url)
        metas = (data.get("metas") or []) if isinstance(data, dict) else []
        for m in metas:
            raw_id = m.get("id") or ""
            clean_id = _clean_imdb(raw_id)
            if not clean_id or clean_id in seen:
                continue
            seen.add(clean_id)
            title = m.get("name") or clean_id
            poster = m.get("poster") or ""
            year = m.get("year") or ""
            is_movie = (m.get("type") == "movie") or (m_type == "movie")
            slug = f"movie:{clean_id}" if is_movie else f"series:{clean_id}"

            score_val = None
            try:
                score_raw = m.get("imdbRating") or m.get("score")
                if score_raw:
                    score_val = float(score_raw)
            except Exception:
                pass

            results.append({
                "id": slug,
                "title": title,
                "poster": poster,
                "year": year,
                "type": "Movie" if is_movie else "Series",
                "score": score_val,
                "duration": m.get("runtime") or "",
                "description": m.get("description") or "",
            })
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    return results


def catalog_movies(page: int = 1, per_page: int = 24, media_type: str = "movie") -> dict:
    """Katalog film / serial terpopuler saat ini dengan upstream pagination skip."""
    page = max(1, int(page or 1))
    skip = (page - 1) * per_page
    url_template = CINEMETA_CATALOG_MOVIE if media_type == "movie" else CINEMETA_CATALOG_SERIES
    url = url_template.format(skip)
    data = _fetch_json(url)
    metas = (data.get("metas") or []) if isinstance(data, dict) else []

    items = []
    seen = set()
    for m in metas:
        raw_id = m.get("id") or ""
        clean_id = _clean_imdb(raw_id)
        if not clean_id or clean_id in seen:
            continue
        seen.add(clean_id)
        is_movie = (media_type == "movie") or (m.get("type") == "movie")
        slug = f"movie:{clean_id}" if is_movie else f"series:{clean_id}"

        score_val = None
        try:
            score_raw = m.get("imdbRating") or m.get("score")
            if score_raw:
                score_val = float(score_raw)
        except Exception:
            pass

        items.append({
            "id": slug,
            "title": m.get("name") or clean_id,
            "poster": m.get("poster") or "",
            "year": m.get("year") or "",
            "type": "Movie" if is_movie else "Series",
            "score": score_val,
            "duration": m.get("runtime") or "",
            "description": m.get("description") or "",
        })

    has_next = len(items) >= per_page
    total_pages = (page + 1) if has_next else page

    return {
        "items": items,
        "page": page,
        "total_pages": max(total_pages, 10),
        "total": len(items),
        "has_next": has_next,
        "media_type": media_type
    }


def get_movie_episodes(slug: str) -> list:
    """Daftar episode / tayangan untuk film atau serial."""
    clean_slug = (slug or "").strip()
    is_series = clean_slug.startswith("series:")
    imdb_id = _clean_imdb(clean_slug.split(":", 1)[-1])

    if not is_series:
        return [{
            "ep": 1,
            "ep_id": "1",
            "title": "Full Movie (Putar Film)",
            "season": 1,
            "episode": 1
        }]

    # Fetch episodes dari Cinemeta series
    url = CINEMETA_DETAIL_SERIES.format(imdb_id)
    data = _fetch_json(url)
    meta = data.get("meta", {}) if isinstance(data, dict) else {}
    vids = meta.get("videos", []) or []

    # Filter season > 0
    regular = sorted([v for v in vids if (v.get("season") or 0) > 0],
                     key=lambda x: (x.get("season", 1), x.get("episode", 1)))
    target_vids = regular if regular else vids

    episodes = []
    for idx, v in enumerate(target_vids):
        s = v.get("season", 1)
        e = v.get("episode", idx + 1)
        name = v.get("title") or v.get("name") or ""
        label = f"S{s} E{e}" + (f": {name}" if name else "")
        episodes.append({
            "ep": idx + 1,
            "ep_id": f"{s}:{e}",
            "season": s,
            "episode": e,
            "title": label
        })

    if not episodes:
        episodes = [{
            "ep": 1,
            "ep_id": "1:1",
            "season": 1,
            "episode": 1,
            "title": "Episode 1"
        }]

    return episodes


def resolve_movie_stream(slug: str, ep: int = 1) -> dict:
    """Resolve stream URL & multi-server embed untuk film / serial TV."""
    clean_slug = (slug or "").strip()
    is_series = clean_slug.startswith("series:")
    imdb_id = _clean_imdb(clean_slug.split(":", 1)[-1])

    season = 1
    episode = ep

    if is_series:
        eps_list = get_movie_episodes(clean_slug)
        target = next((x for x in eps_list if x.get("ep") == ep), None)
        if target:
            season = target.get("season", 1)
            episode = target.get("episode", ep)

    # Cek metadata film dari Cinemeta untuk mengetahui judul dan negara asal
    meta_url = (CINEMETA_DETAIL_SERIES if is_series else CINEMETA_DETAIL_MOVIE).format(imdb_id)
    meta_data = _fetch_json(meta_url)
    meta_obj = (meta_data.get("meta") or {}) if isinstance(meta_data, dict) else {}
    title = meta_obj.get("name") or clean_slug
    country = str(meta_obj.get("country") or "").lower()
    is_indo = ("indonesia" in country) or ("agak laen" in title.lower())

    # Cek ketersediaan stream lokal di Rebahin (khususnya untuk film Indonesia/Sub Indo)
    rb_server = None
    if title:
        try:
            from api import rebahin
            # Bersihkan judul dari simbol untuk pencarian Rebahin
            clean_q = re.sub(r"[:!?\-]+", " ", title).strip()
            rb_search = rebahin.search(clean_q, limit=3)
            if not rb_search and title != clean_q:
                rb_search = rebahin.search(title, limit=3)
            if rb_search:
                rb_slug = rb_search[0].get("id", "")
                if rb_slug.startswith("rebahin:"):
                    rb_slug = rb_slug[len("rebahin:"):]
                rb_stream = rebahin.resolve_stream(rb_slug, ep=episode)
                if rb_stream and rb_stream.get("master"):
                    rb_server = {
                        "name": "🇮🇩 Rebahin (Lokal Sub Indo)",
                        "url": rb_stream.get("master"),
                        "is_m3u8": True,
                        "is_embed": False,
                        "referer": rb_stream.get("referer", "https://rebahinxxi3.mom/")
                    }
        except Exception:
            pass

    # Server list multi-provider dengan VidLink ad-free sebagai server utama
    theme_params = "?autoplay=false&primaryColor=00f2ff&secondaryColor=0d1520&iconColor=00f2ff"
    if is_series:
        servers = [
            {
                "name": "⚡ VidLink (Ad-Free)",
                "url": f"https://vidlink.pro/tv/{imdb_id}/{season}/{episode}{theme_params}",
                "is_embed": True,
                "is_m3u8": False
            },
            {
                "name": "🌐 AutoEmbed (Server 2)",
                "url": f"https://autoembed.co/tv/imdb/{imdb_id}-{season}-{episode}",
                "is_embed": True,
                "is_m3u8": False
            },
            {
                "name": "🎬 VidSrc Net (Server 3)",
                "url": f"https://vidsrc.net/embed/tv/{imdb_id}/{season}/{episode}",
                "is_embed": True,
                "is_m3u8": False
            },
            {
                "name": "🍿 2Embed (Server 4)",
                "url": f"https://www.2embed.cc/embedtv/{imdb_id}&s={season}&e={episode}",
                "is_embed": True,
                "is_m3u8": False
            },
            {
                "name": "📺 MultiEmbed (Server 5)",
                "url": f"https://multiembed.mov/?video_id={imdb_id}&s={season}&e={episode}",
                "is_embed": True,
                "is_m3u8": False
            }
        ]
    else:
        servers = [
            {
                "name": "⚡ VidLink (Ad-Free)",
                "url": f"https://vidlink.pro/movie/{imdb_id}{theme_params}",
                "is_embed": True,
                "is_m3u8": False
            },
            {
                "name": "🌐 AutoEmbed (Server 2)",
                "url": f"https://autoembed.co/movie/imdb/{imdb_id}",
                "is_embed": True,
                "is_m3u8": False
            },
            {
                "name": "🎬 VidSrc Net (Server 3)",
                "url": f"https://vidsrc.net/embed/movie/{imdb_id}",
                "is_embed": True,
                "is_m3u8": False
            },
            {
                "name": "🍿 2Embed (Server 4)",
                "url": f"https://www.2embed.cc/embed/{imdb_id}",
                "is_embed": True,
                "is_m3u8": False
            },
            {
                "name": "📺 MultiEmbed (Server 5)",
                "url": f"https://multiembed.mov/?video_id={imdb_id}",
                "is_embed": True,
                "is_m3u8": False
            }
        ]

    # Cek ketersediaan stream di Dutamovie21
    dm_server = None
    if title:
        try:
            from api import dutamovie
            clean_q = re.sub(r"[:!?\-]+", " ", title).strip()
            dm_search = dutamovie.search(clean_q, limit=3)
            if not dm_search and title != clean_q:
                dm_search = dutamovie.search(title, limit=3)
            if dm_search:
                dm_slug = dm_search[0].get("id", "")
                if dm_slug.startswith("dutamovie:"):
                    dm_slug = dm_slug[len("dutamovie:"):]
                dm_stream = dutamovie.resolve_stream(dm_slug, ep=episode)
                if dm_stream and dm_stream.get("servers"):
                    top_dm = dm_stream["servers"][0]
                    dm_server = {
                        "name": f"🎬 Dutamovie21 ({top_dm.get('name', 'Server')})",
                        "url": top_dm.get("url"),
                        "is_m3u8": False,
                        "is_embed": True,
                        "referer": "https://aubergedelavenir.com/"
                    }
        except Exception:
            pass

    # Prioritaskan Rebahin & Dutamovie jika film lokal Indonesia atau tambahkan sebagai alternatif
    if dm_server:
        if is_indo:
            servers.insert(0, dm_server)
        else:
            servers.insert(2 if rb_server else 1, dm_server)

    if rb_server:
        if is_indo:
            servers.insert(0, rb_server)
        else:
            servers.insert(1, rb_server)

    primary_server = servers[0]

    subtitles = [
        {"lang": "id", "label": "Indonesian (Sub Indo)", "url": "", "default": True},
        {"lang": "en", "label": "English", "url": "", "default": False}
    ]

    return {
        "slug": slug,
        "ep": ep,
        "is_embed": primary_server.get("is_embed", True),
        "is_movie": True,
        "embed_url": primary_server["url"],
        "master": primary_server["url"],
        "variants": [{"q": s["name"], "url": s["url"], "is_embed": s.get("is_embed", True), "is_m3u8": s.get("is_m3u8", False), "referer": s.get("referer", "")} for s in servers],
        "picked": {"q": primary_server["name"], "url": primary_server["url"], "is_embed": primary_server.get("is_embed", True), "is_m3u8": primary_server.get("is_m3u8", False), "referer": primary_server.get("referer", "")},
        "servers": servers,
        "server": primary_server["name"],
        "subtitles": subtitles,
        "sub": None,
        "sub_lang": "Indonesian",
        "referer": primary_server.get("referer", "https://vidlink.pro/"),
        "source": "film"
    }
