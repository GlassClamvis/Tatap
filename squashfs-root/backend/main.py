import sys, os, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asyncio, subprocess, tempfile
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse, FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from config import APP_PORT, APP_HOST, HI_BASE, HI_UA
from database import init_db, get_search_cache, set_search_cache, get_episode_cache, set_episode_cache, add_history, get_history, clear_history, get_setting, set_setting, get_browse_cache, set_browse_cache, get_slug_map, set_slug_map, get_subtitle_cache, set_subtitle_cache, delete_subtitle_cache, get_today_char_count, add_today_char_count
from api import hianime as hi
from api import anilist as al
from api import otakudesu as otaku
from api import rebahin as rebahin_api
from api import movies as movies_api
from api import dutamovie as dutamovie_api
import httpx

frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

from version import __version__ as CURRENT_VERSION
app = FastAPI(title="Tatap", version=CURRENT_VERSION, lifespan=lifespan)

def ok(data):
    return {"success": True, "data": data}
def fail(msg):
    return JSONResponse({"success": False, "error": msg}, status_code=200)

@app.get("/api/ping")
async def ping():
    return ok({"status": "running"})

@app.get("/api/version")
async def get_version():
    return ok({"version": CURRENT_VERSION})

@app.get("/api/update/check")
async def check_update():
    """Pemeriksaan pembaruan versi Tatap secara on-demand via GitHub Releases API.
    Memfilter 4 berkas resmi sesuai aturan paten agent.md:
    1. tatap-release-v<VER>.apk (Official Signed Mobile APK)
    2. tatap-tv-release-v<VER>.apk (Official Signed Android/Google TV APK)
    3. tatap-windows-x64-portable.zip (Windows Portable)
    4. Tatap-x86_64.AppImage (Linux AppImage)
    """
    try:
        url = "https://api.github.com/repos/asfaraguest/tatap/releases/latest"
        headers = {
            "User-Agent": f"Tatap-App/{CURRENT_VERSION} (https://github.com/asfaraguest/tatap)",
            "Accept": "application/vnd.github.v3+json"
        }
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return fail(f"Gagal memeriksa update (HTTP {resp.status_code})")
        rel_data = resp.json()
        tag_name = (rel_data.get("tag_name") or "").strip()
        latest_clean = re.sub(r"^v", "", tag_name)
        curr_clean = re.sub(r"^v", "", CURRENT_VERSION)

        def parse_ver(v_str):
            nums = []
            for part in v_str.split("."):
                m = re.match(r"^\d+", part)
                nums.append(int(m.group(0)) if m else 0)
            return tuple(nums)

        has_update = False
        try:
            has_update = parse_ver(latest_clean) > parse_ver(curr_clean)
        except Exception:
            has_update = latest_clean != curr_clean and bool(latest_clean)

        # Filter strictly the 4 official assets according to agent.md
        assets_out = {
            "android": "",
            "android_tv": "",
            "windows": "",
            "linux": ""
        }
        raw_assets = rel_data.get("assets") or []
        for a in raw_assets:
            fname = (a.get("name") or "").lower()
            dl_url = a.get("browser_download_url") or ""
            if "tatap-tv-release-" in fname and fname.endswith(".apk") and not fname.endswith(".idsig"):
                assets_out["android_tv"] = dl_url
            elif "tatap-release-" in fname and fname.endswith(".apk") and not fname.endswith(".idsig"):
                assets_out["android"] = dl_url
            elif "windows" in fname and fname.endswith(".zip"):
                assets_out["windows"] = dl_url
            elif fname.endswith(".appimage"):
                assets_out["linux"] = dl_url

        return ok({
            "current_version": CURRENT_VERSION,
            "latest_version": latest_clean or tag_name,
            "tag_name": tag_name,
            "has_update": has_update,
            "release_name": rel_data.get("name") or tag_name,
            "body": rel_data.get("body") or "",
            "published_at": rel_data.get("published_at") or "",
            "release_url": rel_data.get("html_url") or "https://github.com/asfaraguest/tatap/releases/latest",
            "assets": assets_out
        })
    except Exception as e:
        return fail(f"Koneksi gagal: {str(e)}")

@app.get("/api/health")
async def health():
    try:
        from curl_cffi import requests as creq
        r = creq.get(HI_BASE + "/", impersonate="chrome124", timeout=10)
        reachable = r.status_code < 500
    except Exception:
        try:
            r = httpx.get(HI_BASE + "/", timeout=10, follow_redirects=True, headers={"User-Agent": HI_UA})
            reachable = r.status_code < 500
        except Exception:
            reachable = False
    return ok({"hianime": HI_BASE, "reachable": reachable})

@app.get("/api/search")
async def search(q: str = Query(""), limit: int = 15, source: str = Query("")):
    q = (q if isinstance(q, str) else "").strip()
    if not q:
        return fail("missing q")

    
    src = (source if isinstance(source, str) else "").strip().lower()
    cache_key = f"{src}|{q.lower()}" if src else q.lower()
    try:
        hit = await get_search_cache(cache_key)
        if hit and any(bool(x.get("poster")) for x in hit):
            return ok({"results": hit, "cached": True})
        loop = asyncio.get_running_loop()
        res = []
        if src in ("film", "movie", "movies"):
            res = await loop.run_in_executor(None, lambda: movies_api.search_movies(q, limit))
        elif src == "otakudesu":
            from api import otakudesu as ot
            res = await loop.run_in_executor(None, lambda: ot.search(q, limit))
        elif src == "rebahin":
            from api import rebahin as rb
            res = await loop.run_in_executor(None, lambda: rb.search(q, limit))
        elif src in ("dutamovie", "duta", "dm21"):
            from api import dutamovie as dm
            res = await loop.run_in_executor(None, lambda: dm.search(q, limit))
        else:
            try:
                res = await loop.run_in_executor(None, lambda: hi.hianime_search(q, limit))
            except Exception:
                res = []
            if not res:
                try:
                    from api import otakudesu as ot
                    res = await loop.run_in_executor(None, lambda: ot.search(q, limit))
                except Exception:
                    pass
            if not res:
                try:
                    from api import rebahin as rb
                    res = await loop.run_in_executor(None, lambda: rb.search(q, limit))
                except Exception:
                    pass
            if not res:
                try:
                    from api import dutamovie as dm
                    res = await loop.run_in_executor(None, lambda: dm.search(q, limit))
                except Exception:
                    pass
            if not res:
                try:
                    res = await loop.run_in_executor(None, lambda: movies_api.search_movies(q, limit))
                except Exception:
                    pass
        if res:
            await set_search_cache(cache_key, res)
        return ok({"results": res, "cached": False})
    except Exception as e:
        return fail(str(e))

@app.get("/api/filters")
async def filters():
    return ok(hi.FILTERS)

@app.get("/api/catalog")
async def catalog(page: int = Query(1, ge=1, le=100), source: str = Query("")):
    """Katalog umum: semua judul, default urut populer."""
    try:
        import json as _json
        src = (source or "").strip().lower()
        key = f"catalog|source={src}|page={page}"
        hit = await get_browse_cache(key)
        if hit:
            hit["cached"] = True
            return ok(hit)
        loop = asyncio.get_running_loop()
        if src in ("film", "movie", "movies"):
            res = await loop.run_in_executor(None, lambda: movies_api.catalog_movies(page))
        elif src in ("dutamovie", "duta", "dm21", "dm"):
            from api import dutamovie as dm
            res = await loop.run_in_executor(None, lambda: dm.catalog(page))
        elif src in ("rebahin", "rb"):
            res = await loop.run_in_executor(None, lambda: rebahin_api.catalog(page))
        else:
            res = await loop.run_in_executor(None, lambda: hi.browse({}, page))
        await set_browse_cache(key, res)
        res["cached"] = False
        return ok(res)
    except Exception as e:
        return fail(str(e))

@app.get("/api/genres")
async def genres(source: str = Query("")):
    """Daftar genre sesuai server aktif (HiAnime, Rebahin, Dutamovie). Cache 24 jam."""
    try:
        src = (source or "").strip().lower()
        key = f"genres|list|source={src}"
        hit = await get_browse_cache(key, ttl=24*3600)
        if hit and hit.get("list"):
            return ok({"list": hit["list"], "source": src, "cached": True})
        loop = asyncio.get_running_loop()
        if src in ("rebahin", "rb"):
            out = await loop.run_in_executor(None, rebahin_api.scrape_genres)
        elif src in ("dutamovie", "duta", "dm21", "dm"):
            out = await loop.run_in_executor(None, dutamovie_api.scrape_genres)
        else:
            out = await loop.run_in_executor(None, hi.scrape_genres)
        await set_browse_cache(key, {"list": out, "source": src})
        return ok({"list": out, "source": src, "cached": False})
    except Exception as e:
        return fail(str(e))

@app.get("/api/seasonal")
async def seasonal(which: str = Query("", pattern="^(now|prev|airing)$|^$"),
                   season: str = Query("", pattern="^(winter|spring|summer|fall)$|^$"),
                   year: int = Query(0, ge=0, le=2100),
                   page: int = Query(1, ge=1, le=100)):
    """Daftar anime per musim / ongoing (AniList dengan fallback HiAnime).
    which=now|prev|airing = musim saat ini / sebelumnya / sedang tayang.
    season+year = musim spesifik (contoh: season=fall year=2024)."""
    try:
        loop = asyncio.get_running_loop()

        # Kasus khusus: Masih Tayang / Airing Ongoing
        if which == "airing":
            key = f"airing_v2|page={page}"
            hit = await get_browse_cache(key, ttl=3600)
            if hit:
                hit["cached"] = True
                return ok(hit)
            hi_data = await loop.run_in_executor(None, lambda: hi.browse({"status": "releasing"}, page))
            if hi_data and hi_data.get("items"):
                hi_data["which"] = "airing"
                await set_browse_cache(key, hi_data)
                hi_data["cached"] = False
                return ok(hi_data)

        is_future = False
        if season and year >= 1900:
            season_name = season
            season_year = year
            cache_id = f"{season}_{year}"
            cur_year, cur_season = al.current_season()
            order = ["winter", "spring", "summer", "fall"]
            try:
                if year > cur_year or (year == cur_year and order.index(season.lower()) > order.index(cur_season.lower())):
                    is_future = True
            except ValueError:
                pass
        else:
            year_cur, name_cur = al.current_season()
            if which == "now":
                season_name, season_year = name_cur, year_cur
            elif which == "prev":
                season_year, season_name = al.prev_season(name_cur, year_cur)
            else:
                season_name, season_year = name_cur, year_cur
            cache_id = which or "now"

        key = f"seasonal_v3|{cache_id}|page={page}"
        hit = await get_browse_cache(key)
        if hit:
            hit["cached"] = True
            hit["season"] = season_name
            hit["year"] = season_year
            return ok(hit)

        status_in = None if is_future else ["RELEASING", "FINISHED"]
        page_data = await loop.run_in_executor(
            None, lambda: al.season_page(season_name, season_year, page, 25, status_in=status_in))

        # Kumpulkan judul dulu, lalu batch-match slug paralel dengan validasi judul & season.
        media_list = (page_data or {}).get("media") or []
        title_pairs = []
        media_by_title = {}
        for m in media_list:
            if not is_future and m.get("status") == "NOT_YET_RELEASED":
                continue
            t_en = (m.get("title") or {}).get("english") or ""
            t_ro = (m.get("title") or {}).get("romaji") or ""
            primary_title = t_en or t_ro or ""
            if not primary_title:
                continue
            alt_title = t_ro if primary_title != t_ro else ""
            title_pairs.append((primary_title, alt_title))
            media_by_title[primary_title] = m
        slug_pairs = await _match_slug_batch(title_pairs) if title_pairs else []
        slug_by_title = {t: s for t, s in slug_pairs}

        items_out = []
        for title, m in media_by_title.items():
            slug = slug_by_title.get(title)
            if not slug:
                continue
            cover = (m.get("coverImage") or {})
            items_out.append({
                "id": slug,
                "title": title,
                "poster": cover.get("large") or cover.get("medium") or "",
                "type": _format_to_type(m.get("format")),
                "eps": m.get("episodes") or 0,
                "duration": (str(m.get("duration") or "") + "m") if m.get("duration") else "",
                "score": (m.get("averageScore") or 0) / 10.0 if m.get("averageScore") else 0,
                "status": (m.get("status") or "").lower(),
                "anilist_id": m.get("id"),
                "site": m.get("siteUrl") or "",
                "matched": True,
            })

        # Fallback jika AniList diblokir ISP / offline / kosong
        hi_data = None
        if not items_out:
            fallback_filter = {"status": "releasing", "sort": "trending"} if which == "now" else {"status": "releasing"}
            if season and year:
                fallback_filter["season"] = season_name
                if not is_future:
                    fallback_filter["status"] = "releasing"
            hi_data = await loop.run_in_executor(None, lambda: hi.browse(fallback_filter, page))
            if hi_data and hi_data.get("items"):
                items_out = hi_data.get("items")

        if hi_data and hi_data.get("items"):
            total_pages = max(1, hi_data.get("total_pages") or 1)
            has_next = page < total_pages
        else:
            page_info = (page_data or {}).get("pageInfo") or {}
            total_pages = max(1, page_info.get("lastPage") or 1)
            has_next = bool(page_info.get("hasNextPage"))

        result = {
            "season": season_name,
            "year": season_year,
            "which": which,
            "items": items_out,
            "page": page,
            "total_pages": total_pages,
            "total_items": len(items_out),
            "has_next": has_next,
            "cached": False,
        }
        await set_browse_cache(key, result)
        return ok(result)
    except Exception as e:
        return fail(str(e))


def _format_to_type(f):
    return {"TV": "TV", "TV_SHORT": "TV", "MOVIE": "Movie", "OVA": "OVA",
            "ONA": "ONA", "SPECIAL": "Special", "MUSIC": "Music"}.get(f or "", "")


def _slug_norm_match(title):
    """Normalisasi judul untuk perbandingan dengan hasil hianime_search.
    Import dari database agar konsisten dengan key yang dipakai slug_map."""
    from database import _slug_norm
    return _slug_norm(title)


def _extract_season_num(t: str) -> int:
    import re
    t = (t or "").lower()
    m = re.search(r"\b(?:season\s*(\d+)|(\d+)(?:nd|rd|th|st)\s*season|part\s*(\d+)|s(\d+))\b", t)
    if m:
        for g in m.groups():
            if g:
                try:
                    return int(g)
                except ValueError:
                    pass
    return 1


def _clean_title_tokens(t: str) -> set:
    import re
    t = re.sub(r"\b(?:season\s*\d+|\d+(?:nd|rd|th|st)\s*season|part\s*\d+|s\d+)\b", "", t or "", flags=re.I)
    t = re.sub(r"[^a-zA-Z0-9\s]", " ", t)
    return set(t.lower().split())


def _is_title_match(target_title: str, candidate_title: str) -> bool:
    import re
    if not target_title or not candidate_title:
        return False
    # 1. Exact normalized match (tanpa spasi & simbol)
    norm_a = re.sub(r"[^a-zA-Z0-9]", "", target_title.lower())
    norm_b = re.sub(r"[^a-zA-Z0-9]", "", candidate_title.lower())
    if norm_a == norm_b:
        return True

    # 2. Validasi nomor season / part (mencegah Season 2 match ke Season 1)
    season_a = _extract_season_num(target_title)
    season_b = _extract_season_num(candidate_title)
    if (season_a > 1 or season_b > 1) and season_a != season_b:
        return False

    # 3. Validasi token overlap
    tokens_a = _clean_title_tokens(target_title)
    tokens_b = _clean_title_tokens(candidate_title)
    if not tokens_a or not tokens_b:
        return False

    stopwords = {"the", "a", "an", "of", "in", "to", "and", "no", "wa", "ga", "ni", "de"}
    sig_common = tokens_a.intersection(tokens_b) - stopwords
    sig_a = tokens_a - stopwords
    sig_b = tokens_b - stopwords

    if not sig_a or not sig_b:
        return (len(tokens_a.intersection(tokens_b)) / max(len(tokens_a), len(tokens_b))) >= 0.75

    overlap = len(sig_common) / max(len(sig_a), len(sig_b))
    return overlap >= 0.60


async def _match_slug_one(loop, title, alt_title=""):
    """Resolve 1 judul -> slug hianime via cache get/set. Return None jika gagal atau tidak cocok."""
    slug = await get_slug_map(title)
    if slug:
        return slug
    try:
        res = await loop.run_in_executor(None, lambda t=title: hi.hianime_search(t, 5))
        if res:
            picked = None
            for c in res:
                c_title = c.get("title", "")
                if _is_title_match(title, c_title) or (alt_title and _is_title_match(alt_title, c_title)):
                    picked = c
                    break
            # Validasi ketat: HANYA gunakan jika benar-benar cocok.
            # JANGAN PERNAH fallback ke res[0] secara buta agar judul & thumbnail tidak tertukar!
            if picked:
                await set_slug_map(title, picked["id"])
                return picked["id"]
    except Exception:
        pass
    return None


# Batas request paralel ke hianime per scrape (mencegah rate-limit).
_SLUG_MATCH_CONCURRENCY = 8


async def _match_slug_batch(items):
    """Match banyak judul ke slug hianime secara paralel.
    Input: list of (primary_title, alt_title) atau list of titles."""
    items = list(items)
    if not items:
        return []
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(_SLUG_MATCH_CONCURRENCY)
    async def one(item):
        if isinstance(item, tuple):
            t, alt = item
        else:
            t, alt = item, ""
        async with sem:
            return t, await _match_slug_one(loop, t, alt)
    pairs = await asyncio.gather(*(one(it) for it in items))
    return pairs


@app.get("/api/schedule")
async def anime_schedule(day: str = Query("today", pattern="^(today|yesterday|tomorrow|all)$")):
    """Jadwal rilis anime 3 hari (kemarin, hari ini, besok) waktu WIB.
    HANYA menampilkan anime yang tersedia di aplikasi Tatap (memiliki slug valid).
    Anime yang tidak ada di aplikasi Tatap otomatis di-remove."""
    try:
        import datetime as _dt
        loop = asyncio.get_running_loop()
        tz_offset = 7 * 3600  # WIB (UTC+7)
        now_utc = int(time.time())
        now_wib = now_utc + tz_offset
        today_midnight_wib = (now_wib // 86400) * 86400
        today_midnight_utc = today_midnight_wib - tz_offset

        y_start_utc = today_midnight_utc - 86400
        t_start_utc = today_midnight_utc
        tm_start_utc = today_midnight_utc + 86400
        tm_end_utc = today_midnight_utc + (2 * 86400) - 1

        cache_key = "schedule_3days_v3"
        cached_data = await get_browse_cache(cache_key, ttl=3600 * 3)

        if not cached_data:
            schedules = await loop.run_in_executor(
                None, lambda: al.anilist_schedules_range(y_start_utc, tm_end_utc, max_pages=3)
            )

            pending = []
            seen_ids = set()
            for s in schedules:
                m = s.get("media") or {}
                mid = m.get("id")
                if not mid or mid in seen_ids:
                    continue
                seen_ids.add(mid)
                t_en = (m.get("title") or {}).get("english") or ""
                t_ro = (m.get("title") or {}).get("romaji") or ""
                primary_title = t_en or t_ro or ""
                if not primary_title:
                    continue
                alt_title = t_ro if primary_title != t_ro else ""
                pending.append((s, primary_title, alt_title))

            slug_pairs = await _match_slug_batch([(t, alt) for _, t, alt in pending]) if pending else []
            slug_by_title = {t: sl for t, sl in slug_pairs}

            buckets = {"yesterday": [], "today": [], "tomorrow": []}

            for s, title, _ in pending:
                slug = slug_by_title.get(title)
                # FILTER KETAT: Yang tidak ada di dalam app Tatap di-REMOVE dari jadwal
                if not slug:
                    continue

                airing_at = int(s["airingAt"])
                dt_wib = _dt.datetime.fromtimestamp(airing_at, _dt.timezone(_dt.timedelta(hours=7)))
                time_str = dt_wib.strftime("%H:%M WIB")
                date_str = dt_wib.strftime("%d %b")

                if airing_at < t_start_utc:
                    day_cat = "yesterday"
                elif airing_at < tm_start_utc:
                    day_cat = "today"
                else:
                    day_cat = "tomorrow"

                cover = (s.get("media") or {}).get("coverImage", {})
                fmt = (s.get("media") or {}).get("format") or "TV"
                score = (s.get("media") or {}).get("averageScore") or 0

                item = {
                    "id": slug,
                    "title": title,
                    "episode": s.get("episode") or 0,
                    "airing_at": airing_at,
                    "time": time_str,
                    "date": date_str,
                    "day": day_cat,
                    "poster": cover.get("large") or cover.get("medium") or "",
                    "type": _format_to_type(fmt),
                    "score": round(score / 10.0, 1) if score else 0.0,
                    "matched": True,
                }
                buckets[day_cat].append(item)

            for k in buckets:
                buckets[k].sort(key=lambda x: x["airing_at"])

            cached_data = {
                "yesterday": buckets["yesterday"],
                "today": buckets["today"],
                "tomorrow": buckets["tomorrow"],
                "total": sum(len(v) for v in buckets.values()),
                "cached": False,
            }
            await set_browse_cache(cache_key, cached_data)

        if day == "all":
            return ok(cached_data)

        target_items = cached_data.get(day, [])
        return ok({
            "items": target_items,
            "day": day,
            "total": len(target_items),
            "counts": {
                "yesterday": len(cached_data.get("yesterday", [])),
                "today": len(cached_data.get("today", [])),
                "tomorrow": len(cached_data.get("tomorrow", [])),
            },
            "cached": cached_data.get("cached", True),
        })
    except Exception as e:
        return fail(str(e))

@app.get("/api/upcoming-episodes")
async def upcoming_episodes(days: int = Query(7, ge=1, le=30), day: str = Query("today")):
    """Penyempurnaan upcoming-episodes yang disinkronkan dengan endpoint schedule 3 hari."""
    try:
        sch_res = await anime_schedule(day=day if day in ("today", "yesterday", "tomorrow") else "today")
        data = sch_res.get("data") if isinstance(sch_res, dict) else None
        if data and "items" in data:
            return ok({
                "items": data["items"],
                "day": data.get("day", "today"),
                "total": data.get("total", len(data["items"])),
                "counts": data.get("counts", {}),
                "cached": data.get("cached", False),
            })
        return sch_res
    except Exception as e:
        return fail(str(e))

@app.get("/api/browse")
async def browse_ep(
    type: str = Query(""), status: str = Query(""), rating: str = Query(""),
    score: str = Query(""), season: str = Query(""), language: str = Query(""),
    sort: str = Query(""), genre: str = Query(""), keyword: str = Query(""),
    sy: str = Query(""), sm: str = Query(""), ey: str = Query(""), em: str = Query(""),
    page: int = Query(1, ge=1, le=100),
    source: str = Query(""),
):
    """Filter bebas — mendukung form filter HiAnime serta browse genre/katalog Rebahin & Dutamovie."""
    try:
        import json as _json
        def _clean(val):
            if val is None or hasattr(val, "default"):
                return ""
            return str(val).strip()

        src = _clean(source).lower()
        genre_clean = _clean(genre)
        page_num = 1
        try:
            page_num = int(page) if not hasattr(page, "default") else 1
        except Exception:
            page_num = 1

        raw_dict = {
            "type": _clean(type), "status": _clean(status), "rating": _clean(rating), "score": _clean(score),
            "season": _clean(season), "language": _clean(language), "sort": _clean(sort), "genre": genre_clean,
            "keyword": _clean(keyword), "sy": _clean(sy), "sm": _clean(sm), "ey": _clean(ey), "em": _clean(em),
            "source": src
        }
        params = {k: v for k, v in raw_dict.items() if v}
        key = "browse|" + _json.dumps(params, sort_keys=True) + f"|page={page_num}"
        hit = await get_browse_cache(key)
        if hit:
            hit["cached"] = True
            return ok(hit)
        loop = asyncio.get_running_loop()
        if src in ("rebahin", "rb"):
            if genre_clean:
                res = await loop.run_in_executor(None, lambda: rebahin_api.browse_genre(genre_clean, page_num))
            else:
                res = await loop.run_in_executor(None, lambda: rebahin_api.catalog(page_num))
        elif src in ("dutamovie", "duta", "dm21", "dm"):
            if genre_clean:
                res = await loop.run_in_executor(None, lambda: dutamovie_api.browse_genre(genre_clean, page_num))
            else:
                res = await loop.run_in_executor(None, lambda: dutamovie_api.catalog(page_num))
        else:
            res = await loop.run_in_executor(None, lambda: hi.browse(params, page_num))

        await set_browse_cache(key, res)
        res["cached"] = False
        return ok(res)
    except Exception as e:
        return fail(str(e))

@app.get("/api/anime/{slug:path}/episodes")
async def episodes(slug: str):
    try:

        cache_key = f"episodes_v1|{slug}"
        cached = await get_browse_cache(cache_key, ttl=6 * 3600)
        if cached:
            cached["cached"] = True
            return ok(cached)
        loop = asyncio.get_running_loop()
        eps = []
        if slug.startswith("movie:") or slug.startswith("series:") or slug.startswith("film:"):
            try:
                raw_eps = await loop.run_in_executor(None, lambda: movies_api.get_movie_episodes(slug))
                if raw_eps:
                    eps = [{"ep": e["ep"], "ep_id": str(e.get("ep_id") or e["ep"]), "title": e.get("title", f"Episode {e['ep']}")} for e in raw_eps]
            except Exception:
                pass
        elif slug.startswith("rebahin:"):
            try:
                rb_slug = slug[len("rebahin:"):]
                rb_eps = await loop.run_in_executor(None, lambda: rebahin_api.get_episodes(rb_slug))
                if rb_eps:
                    eps = [{"ep": e["ep"], "ep_id": str(e["ep"])} for e in rb_eps]
            except Exception:
                pass
        elif slug.startswith("dutamovie:"):
            try:
                dm_eps = await loop.run_in_executor(None, lambda: dutamovie_api.get_episodes(slug))
                if dm_eps:
                    eps = [{"ep": e["ep"], "ep_id": str(e.get("ep_id") or e["ep"]), "title": e.get("title", f"Episode {e['ep']}")} for e in dm_eps]
            except Exception:
                pass
        else:
            try:
                eps = await loop.run_in_executor(None, lambda: hi.hianime_episodes(slug))
            except Exception:
                try:
                    otaku_slug = slug[len("otakudesu:"):] if slug.startswith("otakudesu:") else slug
                    otaku_eps = await loop.run_in_executor(None, lambda: otaku.get_episodes(otaku_slug))
                    if otaku_eps:
                        eps = [{"ep": e["ep"], "ep_id": str(e["ep"])} for e in otaku_eps]
                except Exception:
                    pass
                if not eps:
                    try:
                        rb_slug = slug[len("rebahin:"):] if slug.startswith("rebahin:") else slug
                        rb_eps = await loop.run_in_executor(None, lambda: rebahin_api.get_episodes(rb_slug))
                        if rb_eps:
                            eps = [{"ep": e["ep"], "ep_id": str(e["ep"])} for e in rb_eps]
                    except Exception:
                        pass
                if not eps:
                    try:
                        dm_eps = await loop.run_in_executor(None, lambda: dutamovie_api.get_episodes(slug))
                        if dm_eps:
                            eps = [{"ep": e["ep"], "ep_id": str(e.get("ep_id") or e["ep"]), "title": e.get("title", f"Episode {e['ep']}")} for e in dm_eps]
                    except Exception:
                        pass
        if not eps:
            return fail("Daftar episode tidak ditemukan")
        data = {"slug": slug, "episodes": eps, "total": len(eps)}
        await set_browse_cache(cache_key, data)
        data["cached"] = False
        return ok(data)
    except Exception as e:
        return fail(str(e))

@app.get("/api/anime/{slug:path}/relations")
async def anime_relations_endpoint(slug: str, title: str = Query("")):
    """Ambil daftar season/prekuel/sekuel terkait untuk anime yang sedang dibuka."""
    try:

        loop = asyncio.get_running_loop()
        cache_key = f"relations_v1|{slug}"
        cached = await get_browse_cache(cache_key, ttl=86400 * 3) # Cache 3 hari
        if cached:
            return ok(cached)

        if slug.startswith("dutamovie:") or slug.startswith("rebahin:") or slug.startswith("movie:"):
            return ok({"current_slug": slug, "relations": []})

        # Gunakan title dari query parameter atau tebak dari slug
        search_query = title.strip() if title else slug.rsplit("-", 1)[0].replace("-", " ")
        raw_relations = await loop.run_in_executor(None, lambda: al.anime_relations(search_query))

        results = []
        for r in raw_relations:
            rel_type = r.get("relation", "")
            r_title = r.get("title", "")
            r_romaji = r.get("title_romaji", "")
            r_year = r.get("year")
            r_fmt = r.get("format", "TV")
            r_poster = r.get("poster", "")
            is_origin = r.get("is_origin", False)

            # Cari slug HiAnime yang cocok untuk relasi ini
            matched_slug = await _match_slug_one(loop, r_title, r_romaji)
            if not matched_slug and r_romaji:
                matched_slug = await _match_slug_one(loop, r_romaji, r_title)

            # Jika sekuel belum memiliki video atau belum rilis (tidak punya slug), lewati agar tidak menyesatkan
            if rel_type in ("SEQUEL", "ALTERNATIVE", "SUMMARY") and not matched_slug:
                continue

            # Buat label yang mudah dimengerti user (misal: "Season 1", "Prekuel", "Sekuel", "Movie")
            label = "Terkait"
            season_num = _extract_season_num(r_title) or _extract_season_num(r_romaji)
            if is_origin or (rel_type == "PREQUEL" and season_num == 1 and "season" not in r_title.lower()):
                label = "Season 1"
            elif rel_type == "PREQUEL":
                label = f"Season {season_num}" if season_num > 1 else "Prekuel"
            elif rel_type == "SEQUEL":
                label = f"Season {season_num}" if season_num > 1 else "Sekuel"
            elif r_fmt == "MOVIE":
                label = "Movie"
            elif r_fmt in ("OVA", "ONA", "SPECIAL"):
                label = r_fmt

            results.append({
                "relation": rel_type,
                "label": label,
                "title": r_title,
                "title_romaji": r_romaji,
                "year": r_year,
                "format": r_fmt,
                "poster": r_poster,
                "slug": matched_slug,
                "is_origin": is_origin
            })

        # Urutkan: Season 1 / Origin paling pertama (-1), disusul PREQUEL berurutan tahun (2018 -> 2021), SEQUEL, MOVIE
        def sort_key(x):
            if x.get("is_origin") or x.get("label") == "Season 1":
                return (-1, x.get("year") or 0)
            order_map = {"PREQUEL": 0, "PARENT": 1, "SEQUEL": 2, "ALTERNATIVE": 3, "SIDE_STORY": 4, "SUMMARY": 5}
            return (order_map.get(x["relation"], 9), x.get("year") or 9999)

        results.sort(key=sort_key)

        data = {"current_slug": slug, "relations": results}
        await set_browse_cache(cache_key, data)
        return ok(data)
    except Exception as e:
        return fail(str(e))


@app.get("/api/stream/resolve")
async def resolve(slug: str = Query(""), ep: int = Query(1), mode: str = Query("sub"), q: str = Query("best"), source: str = Query("")):
    try:

        mode = "dub" if mode.lower() == "dub" else "sub"
        pref_source = (await get_setting("preferred_source", "hianime")).lower()
        active_source = (source or pref_source or "hianime").lower()

        # Cache key mencakup source agar stream tidak tertukar
        cache_slug = f"{active_source}:{slug}" if active_source != "hianime" else slug
        hit = await get_episode_cache(cache_slug, ep, mode)
        if not hit and mode == "sub":
            hit = await get_episode_cache(cache_slug, ep, "dub")
        elif not hit and mode == "dub":
            hit = await get_episode_cache(cache_slug, ep, "sub")
        async def _check_and_prewarm(ep_data):
            try:
                sub_lang = (await get_setting("sub_lang", "Indonesian")).strip().lower()
                auto_tr = await get_setting("tatap_translate", "1")
                # Jika preferensi pengguna adalah Indonesia atau auto-translate aktif
                if sub_lang in ("indonesian", "id") or auto_tr in ("1", "true"):
                    subs = ep_data.get("subtitles") or []
                    en_url = ""
                    for s in subs:
                        l = (s.get("lang") or "").lower()
                        lbl = (s.get("label") or "").lower()
                        if l == "en" or "english" in lbl or lbl.startswith("eng"):
                            en_url = s.get("url") or ""
                            break
                    if not en_url and ep_data.get("sub"):
                        sub_l = (ep_data.get("sub_lang") or "").lower()
                        if "arab" not in sub_l and sub_l != "ar":
                            en_url = ep_data.get("sub") or ""
                    if en_url:
                        asyncio.create_task(_prewarm_sub_translation(en_url, ep_data.get("referer") or "", "en", "id"))
            except Exception:
                pass

        if hit:
            # Pastikan subtitle yang tersimpan di cache lama dinormalisasi ulang
            # sehingga tidak pernah mengembalikan Arabic sebagai default track.
            if hit.get("subtitles"):
                hit["subtitles"] = hi._normalize_subtitles(hit["subtitles"], referer=hit.get("referer") or "")
                def_track = next((s for s in hit["subtitles"] if s.get("default")), None)
                if def_track:
                    hit["sub"] = def_track["url"]
                    hit["sub_lang"] = def_track["label"]
            elif hit.get("sub_lang", "").lower().startswith("ar") or "arab" in hit.get("sub_lang", "").lower():
                hit["sub"] = None
                hit["sub_lang"] = None

            picked = hi.select_quality(hit["variants"], q)
            hit["picked"] = picked
            hit["cached"] = True
            hit["subtitles"] = hit.get("subtitles") or []
            hit["source"] = active_source
            await _check_and_prewarm(hit)
            return ok(hit)

        loop = asyncio.get_running_loop()
        got = None
        last_error = None

        if slug.startswith("movie:") or slug.startswith("series:") or active_source in ("film", "movie", "movies"):
            try:
                active_source = "film"
                got = await loop.run_in_executor(None, lambda: movies_api.resolve_movie_stream(slug, ep))
            except Exception as e:
                last_error = e
        elif active_source in ("dutamovie", "duta", "dm21") or slug.startswith("dutamovie:"):
            try:
                active_source = "dutamovie"
                dm_slug = slug[len("dutamovie:"):] if slug.startswith("dutamovie:") else slug
                got = await loop.run_in_executor(None, lambda: dutamovie_api.resolve_stream(dm_slug, ep))
            except Exception as e:
                last_error = e
                if source == "auto" or not source:
                    try:
                        got = await loop.run_in_executor(None, lambda: rebahin_api.resolve_stream(slug, ep))
                        active_source = "rebahin"
                        cache_slug = f"rebahin:{slug}"
                    except Exception:
                        pass
        elif active_source == "rebahin":
            try:
                rb_slug = slug[len("rebahin:"):] if slug.startswith("rebahin:") else slug
                got = await loop.run_in_executor(None, lambda: rebahin_api.resolve_stream(rb_slug, ep))
            except Exception as e:
                last_error = e
                if source == "auto" or not source:
                    try:
                        got = await loop.run_in_executor(None, lambda: dutamovie_api.resolve_stream(slug, ep))
                        active_source = "dutamovie"
                        cache_slug = f"dutamovie:{slug}"
                    except Exception:
                        try:
                            got = await loop.run_in_executor(None, lambda: otaku.resolve_stream(slug, ep))
                            active_source = "otakudesu"
                            cache_slug = f"otakudesu:{slug}"
                        except Exception:
                            try:
                                maps = await loop.run_in_executor(None, lambda: hi.hianime_episodes(slug))
                                got = await loop.run_in_executor(None, lambda: hi.hianime_m3u8(maps, ep, mode, slug))
                                active_source = "hianime"
                                cache_slug = slug
                            except Exception:
                                pass
        elif active_source == "otakudesu":
            try:
                otaku_slug = slug[len("otakudesu:"):] if slug.startswith("otakudesu:") else slug
                got = await loop.run_in_executor(None, lambda: otaku.resolve_stream(otaku_slug, ep))
            except Exception as e:
                last_error = e
                # Fallback ke rebahin lalu hianime kalau user pakai auto
                if source == "auto" or not source:
                    try:
                        got = await loop.run_in_executor(None, lambda: rebahin_api.resolve_stream(slug, ep))
                        active_source = "rebahin"
                        cache_slug = f"rebahin:{slug}"
                    except Exception:
                        try:
                            maps = await loop.run_in_executor(None, lambda: hi.hianime_episodes(slug))
                            got = await loop.run_in_executor(None, lambda: hi.hianime_m3u8(maps, ep, mode, slug))
                            active_source = "hianime"
                            cache_slug = slug
                        except Exception:
                            pass
        else:
            try:
                maps = await loop.run_in_executor(None, lambda: hi.hianime_episodes(slug))
                got = await loop.run_in_executor(None, lambda: hi.hianime_m3u8(maps, ep, mode, slug))
            except Exception as e:
                last_error = e
                # Fallback ke otakudesu lalu rebahin jika hianime gagal
                if source == "auto" or not source:
                    try:
                        got = await loop.run_in_executor(None, lambda: otaku.resolve_stream(slug, ep))
                        active_source = "otakudesu"
                        cache_slug = f"otakudesu:{slug}"
                    except Exception:
                        try:
                            got = await loop.run_in_executor(None, lambda: rebahin_api.resolve_stream(slug, ep))
                            active_source = "rebahin"
                            cache_slug = f"rebahin:{slug}"
                        except Exception:
                            try:
                                got = await loop.run_in_executor(None, lambda: dutamovie_api.resolve_stream(slug, ep))
                                active_source = "dutamovie"
                                cache_slug = f"dutamovie:{slug}"
                            except Exception:
                                pass

        if not got:
            raise last_error or RuntimeError("Stream gagal di-resolve dari semua sumber")

        got["source"] = active_source
        got["picked"] = hi.select_quality(got["variants"], q)
        got["cached"] = False
        got["subtitles"] = got.get("subtitles") or []
        actual_mode = got.get("mode") or mode
        got["mode"] = actual_mode

        # Simpan cache episode
        await set_episode_cache(cache_slug, ep, mode, got["master"], got["variants"],
                                got.get("sub"), got.get("sub_lang"),
                                got.get("referer"), got.get("server"),
                                subtitles=got["subtitles"])
        if actual_mode != mode:
            await set_episode_cache(cache_slug, ep, actual_mode, got["master"], got["variants"],
                                    got.get("sub"), got.get("sub_lang"),
                                    got.get("referer"), got.get("server"),
                                    subtitles=got["subtitles"])
        await _check_and_prewarm(got)
        return ok(got)
    except Exception as e:
        return fail(str(e))

def _is_m3u8_url(url: str, ctype: str = "") -> bool:
    """Deteksi akurat apakah URL adalah playlist m3u8 atau segmen video/audio."""
    if "mpegurl" in (ctype or "").lower():
        return True
    path = url.split("?", 1)[0].lower()
    if path.endswith(".m3u8") or path.endswith("/m3u8"):
        return True
    if any(path.endswith(ext) for ext in (".ts", ".ts.jpg", ".jpg", ".jpeg", ".png", ".mp4", ".m4s", ".aac", ".mp3", ".vtt")):
        return False
    if any(p in url.lower() for p in ("/hls/playlist", "/api/hls", "format=m3u8", "output=m3u8", ".m3u8?")):
        return True
    return False


@app.get("/api/player/video")
async def proxy_video(url: str = Query(""), referer: str = Query("")):
    # Proxy cepat: koneksi dipakai ulang, segmen di-stream (tanpa buffer penuh),
    # Range diteruskan supaya seek tidak unduh ulang dari awal.
    from fastapi import Request
    from fastapi.responses import StreamingResponse as _SR
    if not url.startswith("http"):
        return Response(status_code=400)
    from api.hianime import SEG_RE, SEG_KEY, SEG_IV, STRIP_BYTES, STRIP_RE
    import re as _re
    m = SEG_RE.search(url)
    if m:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            import base64 as _b64
            tok = m.group(1)
            s = tok.replace("-", "+").replace("_", "/")
            s += "=" * (-len(s) % 4)
            raw = _b64.b64decode(s)
            d = Cipher(algorithms.AES(SEG_KEY), modes.CBC(SEG_IV)).decryptor()
            pt = d.update(raw) + d.finalize()
            real = pt.decode("utf-8", errors="strict").strip().strip("\x00").strip()
            url = real if real.startswith("http") else url
        except Exception:
            pass

    is_m3u8 = _is_m3u8_url(url)
    media_type = "application/vnd.apple.mpegurl" if is_m3u8 else "video/mp2t"

    if not referer:
        if any(h in url for h in ("dramahot.top", "drama1.cfd", "zokoanime")):
            referer = "https://zokoanime.video/"
        elif any(h in url for h in ("megacloud", "rapid-cloud")):
            referer = "https://megacloud.blog/"
        elif any(h in url for h in ("puterin.biz", "putarin.xyz", "stream121.space")):
            referer = "https://puterin.biz/"
        elif any(h in url for h in ("phantomharbor", "nexabloom", "silverorbit", "megaplay", "vidtube", "vidplay")):
            referer = "https://megaplay.buzz/"

    # Jika host terdeteksi diblokir DPI ISP, gunakan TLS desync murni (aman dari Sangfor)
    from api.hianime import _host_from, _BLOCKED_DPI_HOSTS
    host = _host_from(url)
    if host in _BLOCKED_DPI_HOSTS:
        return _SR(_pipe_desync_video(url, referer), media_type=media_type,
                   headers={"Access-Control-Allow-Origin": "*"})

    return _SR(_pipe_video(url, referer), media_type=media_type,
               headers={"Access-Control-Allow-Origin": "*"})


def _rewrite_m3u8_content(txt: str, base_url: str, referer: str) -> str:
    """Tulis ulang m3u8 dan pastikan audio codec & sub-manifests (audio, subtitles, init) ter-proxy."""
    import urllib.parse as _up
    import re as _re
    base = base_url.rsplit("/", 1)[0] + "/"
    out = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s:
            out.append(ln)
            continue
        # Jika master playlist menyertakan STREAM-INF, pastikan audio codec (mp4a) ada di CODECS
        # agar browser/Hls.js tahu ada stream audio AAC dan menyiapkan audio SourceBuffer
        if s.startswith("#EXT-X-STREAM-INF:"):
            if "CODECS=" not in s:
                s += ',CODECS="avc1.64001f,mp4a.40.2"'
            elif not any(ac in s.lower() for ac in ("mp4a", "aac", "opus", "mp3")):
                s = _re.sub(r'CODECS="([^"]+)"', r'CODECS="\1,mp4a.40.2"', s)

        if s.startswith("#"):
            # Rewrite URI="..." di dalam tag seperti #EXT-X-MEDIA (audio/subtitles), #EXT-X-MAP, #EXT-X-KEY
            if "URI=" in s:
                def _rep_uri(m):
                    raw_uri = m.group(1) or m.group(2) or m.group(3)
                    absu = raw_uri if raw_uri.startswith("http") else _up.urljoin(base, raw_uri)
                    return f'URI="/api/player/video?url={_up.quote(absu, safe="")}&referer={_up.quote(referer or "", safe="")}"'
                s = _re.sub(r'URI=(?:"([^"]+)"|\'([^\']+)\'|([^,\s]+))', _rep_uri, s)
            out.append(s)
            continue

        absu = s if s.startswith("http") else _up.urljoin(base, s)
        out.append(f"/api/player/video?url={_up.quote(absu, safe='')}&referer={_up.quote(referer or '', safe='')}")
    return "\n".join(out)


async def _pipe_desync_video(url: str, referer: str):
    """Streaming video via TLS Client Hello Desynchronization (Direct TCP 443 tanpa VPN)."""
    from api.desync import tls_desync_request, tls_desync_stream
    import asyncio
    
    headers = {"Referer": referer} if referer else {}
    loop = asyncio.get_running_loop()
    
    # Playlist m3u8: baca penuh dan rewrite URL agar segmen tetap lewat proxy Tatap
    if _is_m3u8_url(url):
        body = await loop.run_in_executor(None, lambda: tls_desync_request(url, headers=headers))
        try:
            txt = body.decode("utf-8", errors="strict")
        except Exception:
            return
        if "#EXTM3U" not in txt:
            return
        yield _rewrite_m3u8_content(txt, url, referer).encode("utf-8")
        return

    # Segmen TS: stream per bongkah via desync TLS generator
    async for chunk in tls_desync_stream(url, headers=headers):
        if chunk:
            yield chunk


_direct_client = None

def _get_video_client(url: str):
    """Direct client murni untuk video normal (Megaplay, Otakudesu, dll.)."""
    global _direct_client
    import httpx as _hx
    if _direct_client is None:
        limits = _hx.Limits(max_connections=60, max_keepalive_connections=30, keepalive_expiry=90.0)
        _direct_client = _hx.AsyncClient(
            follow_redirects=True,
            timeout=_hx.Timeout(30.0, connect=15.0),
            limits=limits,
            http2=False
        )
    return _direct_client


async def _pipe_video(url: str, referer: str):
    import urllib.parse as _up
    import asyncio as _asyncio
    from api.hianime import STRIP_BYTES as _SB, STRIP_RE as _SR2
    c = _get_video_client(url)

    headers = {"User-Agent": HI_UA}
    if referer:
        headers["Referer"] = referer

    for attempt in range(2):
        try:
            async with c.stream("GET", url, headers=headers) as r:
                if r.status_code >= 400:
                    if attempt == 0:
                        await _asyncio.sleep(0.3)
                        continue
                    print(f"[Video Proxy Error] Upstream status {r.status_code} for {url[:70]}")
                    return
                ctype = r.headers.get("content-type", "")
                is_playlist = _is_m3u8_url(url, ctype)
                if is_playlist:
                    body = await r.aread()
                    try:
                        txt = body.decode("utf-8", errors="strict")
                    except Exception:
                        return
                    if "#EXTM3U" not in txt:
                        return
                    yield _rewrite_m3u8_content(txt, url, referer).encode("utf-8")
                    return

                skipped = 0
                need_strip = bool(_SR2.search(url))
                async for chunk in r.aiter_bytes(65536):
                    if need_strip and skipped < _SB:
                        cut = min(len(chunk), _SB - skipped)
                        skipped += cut
                        chunk = chunk[cut:]
                        if not chunk:
                            continue
                    if chunk:
                        yield chunk
                return
        except Exception as e:
            if attempt == 0:
                await _asyncio.sleep(0.3)
                continue
            # Jika 2x attempt gagal (RST, timeout, DNS), tandai host dan coba TLS desync
            try:
                from api.hianime import _host_from, _BLOCKED_DPI_HOSTS
                host = _host_from(url)
                _BLOCKED_DPI_HOSTS.add(host)
                async for chunk in _pipe_desync_video(url, referer):
                    yield chunk
                return
            except Exception:
                return

async def _fetch_sub_text(target_url, ref):
    """Helper fetcher yang mendukung desync bila host terblokir DPI atau butuh referer khusus."""
    from api.hianime import _host_from, _BLOCKED_DPI_HOSTS
    h = _host_from(target_url)

    candidates = []
    if ref:
        candidates.append(ref)

    # Domain-specific smart prioritization (Megaplay CDN butuh origin megaplay)
    t_low = target_url.lower()
    if any(k in t_low for k in ("broforgotsave", "stellarfrontier", "megaplay", "megacloud")):
        candidates.extend(["https://megaplay.buzz/", "https://megaplay.top/", "https://megacloud.tv/"])
    if any(k in t_low for k in ("dramahot", "zokoanime")):
        candidates.extend(["https://zokoanime.video/", "https://dramahot.top/"])

    for f_ref in ("https://megaplay.buzz/", "https://megaplay.top/", "https://zokoanime.video/", "https://megacloud.blog/", "https://hianime.at/", "https://hianime.to/", ""):
        if f_ref not in candidates:
            candidates.append(f_ref)

    last_err = None
    for r_head in candidates:
        headers = {"User-Agent": HI_UA}
        if r_head:
            headers["Referer"] = r_head

        # 1. Coba via TLS desync jika host masuk daftar DPI atau host CDN streaming
        if h in _BLOCKED_DPI_HOSTS or "dramahot" in h or "zokoanime" in h:
            try:
                from api.desync import tls_desync_request
                loop = asyncio.get_running_loop()
                raw = await loop.run_in_executor(None, lambda: tls_desync_request(target_url, headers=headers))
                txt = raw.decode("utf-8", errors="replace")
                if "WEBVTT" in txt or len(txt) > 200:
                    return txt
            except Exception as e:
                last_err = e

        # 2. Coba direct request via httpx
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=12.0) as c:
                r = await c.get(target_url, headers=headers)
                if r.status_code == 200 and ("WEBVTT" in r.text or len(r.text) > 200):
                    return r.text
        except Exception as e:
            last_err = e
            # Jika direct gagal (koneksi terputus/RST), coba desync
            try:
                from api.desync import tls_desync_request
                _BLOCKED_DPI_HOSTS.add(h)
                loop = asyncio.get_running_loop()
                raw = await loop.run_in_executor(None, lambda: tls_desync_request(target_url, headers=headers))
                txt = raw.decode("utf-8", errors="replace")
                if "WEBVTT" in txt or len(txt) > 200:
                    return txt
            except Exception as e2:
                last_err = e2

    if last_err:
        raise last_err
    raise RuntimeError("Gagal mengambil subtitle: upstream mengembalikan respons kosong atau tidak valid")


_SUB_INFLIGHT = {}


def _is_valid_id_subtitle(vtt_text: str) -> bool:
    """True jika subtitle memiliki kosakata bahasa Indonesia wajar (mencegah cache poisoning teks sumber atau kuota MyMemory)."""
    if not vtt_text or len(vtt_text.strip()) < 50:
        return True
    if "MYMEMORY WARNING" in vtt_text or "translated.net" in vtt_text:
        return False
    return bool(re.search(r"\b(yang|dan|tidak|aku|kamu|di|ini|itu|bisa|ada|nggak|udah|cuma|banget|siapa|kenapa)\b", vtt_text, re.IGNORECASE))


async def _get_validated_subtitle_cache(key: str, lang: str = "id", ttl: int = 7 * 24 * 3600):
    """Ambil cache subtitle dengan validasi anti-poisoning."""
    hit = await get_subtitle_cache(key, ttl=ttl)
    if hit:
        if (lang or "").lower() == "id" and not _is_valid_id_subtitle(hit):
            try:
                await delete_subtitle_cache(key)
            except Exception:
                pass
            return None
        return hit
    return None


async def _prewarm_sub_translation(url: str, referer: str, src: str = "en", lang: str = "id"):
    """Prefetch subtitle translate di latar belakang jika belum ada di cache."""
    if not url or not url.startswith("http") or not lang or lang == src:
        return
    import hashlib
    base_hash = hashlib.sha1((url + "|" + (referer or "") + "|" + lang).encode("utf-8")).hexdigest()
    key_gtx = "sub2|gtx|" + base_hash
    hit = await _get_validated_subtitle_cache(key_gtx, lang=lang)
    if hit is not None:
        return

    job_key = f"{base_hash}|{lang}"
    fut = _SUB_INFLIGHT.get(job_key)
    if fut is None:
        key_gtxplus = "sub2|gtx+|" + base_hash
        key_aigtx = "sub2|aigtx|" + base_hash
        key_llm = "sub2|llm|" + base_hash
        try:
            from api.translate import log_translate
            log_translate(f"Prefetch subtitle [{lang}] dimulai di background...")
        except Exception:
            pass
        fut = asyncio.ensure_future(_translate_sub_job(url, referer, src, lang, key_llm, key_gtxplus, _fetch_sub_text, key_gtx=key_gtx, requested_mode="gtx"))
        _SUB_INFLIGHT[job_key] = fut
        fut.add_done_callback(lambda _f, k=job_key: _SUB_INFLIGHT.pop(k, None))


@app.get("/favicon.ico")
@app.head("/favicon.ico")
async def favicon():
    fav = os.path.join(frontend_dir, "favicon.ico")
    if os.path.exists(fav):
        return FileResponse(fav, media_type="image/x-icon")
    return Response(status_code=204)


@app.get("/api/player/sub")
async def proxy_sub(url: str = Query(""),
                   referer: str = Query(""),
                   lang: str = Query("", pattern="^(en|id|ja|es|fr|de|pt|ko|zh)$|^$"),
                   src: str = Query("en", pattern="^(en|ja|es|fr|de|pt|ko|zh)$"),
                   mode: str = Query("", pattern="^(gtx|gtx\\+|aigtx|ai|)$"),
                   refresh: bool = Query(False)):
    """Proxy subtitle VTT. Menjalankan translasi multi-tier dengan deduplikasi inflight
    dan proteksi cache poisoning."""
    if not url.startswith("http"):
        return Response(status_code=400)

    # Lang kosong atau sama dengan sumber -> return source apa adanya
    if not lang or lang == src:
        try:
            content = await _fetch_sub_text(url, referer)
            return Response(content=content, media_type="text/vtt")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"gagal mengambil subtitle: {e}")

    import hashlib
    base_hash = hashlib.sha1(
        (url + "|" + (referer or "") + "|" + lang).encode("utf-8")
    ).hexdigest()
    key_gtxplus = "sub2|gtx+|" + base_hash
    key_aigtx = "sub2|aigtx|" + base_hash
    key_gtx = "sub2|gtx|" + base_hash
    key_llm = "sub2|llm|" + base_hash

    if refresh:
        for k in (key_gtx, key_gtxplus, key_aigtx, key_llm, "sub2|mt|" + base_hash):
            try:
                await delete_subtitle_cache(k)
            except Exception:
                pass

    req_mode = "gtx+" if mode in ("gtx+", "aigtx") else (mode or "gtx")

    # Periksa cache lokal jika tidak dalam mode refresh
    if not refresh:
        if req_mode == "gtx":
            hit = await _get_validated_subtitle_cache(key_gtx, lang=lang)
            if hit:
                resp = Response(content=hit, media_type="text/vtt")
                resp.headers["X-Translate-Tier"] = "cached-gtx"
                return resp
        elif req_mode in ("gtx+", "aigtx"):
            hit = await _get_validated_subtitle_cache(key_gtxplus, lang=lang)
            if not hit:
                hit = await _get_validated_subtitle_cache(key_aigtx, lang=lang)
            if not hit:
                hit = await _get_validated_subtitle_cache("sub2|mt|" + base_hash, lang=lang)
            if hit:
                resp = Response(content=hit, media_type="text/vtt")
                resp.headers["X-Translate-Tier"] = "cached-gtx+"
                return resp
        elif req_mode == "ai":
            hit = await _get_validated_subtitle_cache(key_llm, lang=lang)
            if hit:
                resp = Response(content=hit, media_type="text/vtt")
                resp.headers["X-Translate-Tier"] = "cached-llm"
                return resp
        else:
            for k, label in ((key_gtx, "cached-gtx"), (key_gtxplus, "cached-gtx+"), (key_aigtx, "cached-gtx+"), (key_llm, "cached-llm")):
                hit = await _get_validated_subtitle_cache(k, lang=lang)
                if hit:
                    resp = Response(content=hit, media_type="text/vtt")
                    resp.headers["X-Translate-Tier"] = label
                    return resp

    # Satukan eksekusi translasi agar tidak menduplikasi request bersamaan untuk mode yang sama
    job_key = f"{base_hash}|{lang}|{req_mode}"
    fut = _SUB_INFLIGHT.get(job_key)
    if fut is None:
        fut = asyncio.ensure_future(
            _translate_sub_job(url, referer, src, lang, key_llm, key_gtxplus, _fetch_sub_text, key_gtx=key_gtx, requested_mode=req_mode)
        )
        _SUB_INFLIGHT[job_key] = fut
        fut.add_done_callback(lambda _f, k=job_key: _SUB_INFLIGHT.pop(k, None))

    try:
        new_text, tier = await asyncio.shield(fut)
    except HTTPException:
        raise
    except Exception as e:
        # Fallback ke teks asli tanpa menyimpan ke cache
        try:
            raw_text = await _fetch_sub_text(url, referer)
            resp = Response(content=raw_text, media_type="text/vtt")
            resp.headers["X-Translate-Tier"] = "source-fallback"
            resp.headers["X-Translate-Error"] = str(e)[:120]
            return resp
        except Exception:
            raise HTTPException(status_code=502, detail=f"gagal memproses subtitle: {e}")

    resp = Response(content=new_text, media_type="text/vtt")
    resp.headers["X-Translate-Tier"] = tier.get("level", "source")
    if tier.get("model"):
        resp.headers["X-Translate-Model"] = re.sub(r"[^\w.:/\-]", "", str(tier["model"]))[:60]
    if tier.get("gtx_lines"):
        resp.headers["X-Translate-Mixed"] = f'{tier.get("gtx_lines")}/{tier.get("total", 0)}'
    if tier.get("error"):
        clean_err = re.sub(r"[\r\n]+", " ", str(tier["error"])).strip()
        resp.headers["X-Translate-Error"] = clean_err.encode("latin-1", "replace").decode("latin-1")[:200]
    return resp


async def _llm_enabled():
    """Tier aktif kalau ada API key, atau endpoint LLM lokal (Ollama di localhost)."""
    from api.translate import is_local_llm
    apikey = await get_setting("translate_apikey", "")
    apiurl = await get_setting("translate_apiurl", "")
    return bool(apikey) or is_local_llm(apiurl)


async def _translate_sub_job(url, referer, src, lang, key_llm, key_gtxplus, fetcher, key_gtx=None, requested_mode="gtx"):
    """Fetch + translate + cache. Return (vtt_text, tier_dict)."""
    if not key_gtx:
        import hashlib
        b_hash = hashlib.sha1((url + "|" + (referer or "") + "|" + lang).encode("utf-8")).hexdigest()
        key_gtx = "sub2|gtx|" + b_hash
    try:
        text = await fetcher(url, referer)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"gagal mengambil subtitle: {e}")
    try:
        from api.translate import parse_vtt, build_vtt
        cues = parse_vtt(text)
        if not cues:
            return text, {"level": "source", "error": "Subtitle kosong atau format tidak didukung"}
        tier = await _translate_with_fallback(cues, src, lang, requested_mode=requested_mode)
        new_text = build_vtt(tier["cues"])
    except Exception as e:
        return text, {"cues": None, "level": "source", "error": str(e)}

    lvl = tier.get("level")
    # PENTING: Dilarang menyimpan teks sumber (untranslated) atau hasil kaku MyMemory ke dalam cache berkualitas tinggi
    if lvl not in ("source", "source-fallback", "tier4", "mymemory"):
        if (lang or "").lower() != "id" or _is_valid_id_subtitle(new_text):
            if lvl in ("tier1", "gtx"):
                await set_subtitle_cache(key_gtx, new_text)
            elif lvl in ("tier2", "gtx+", "aigtx"):
                await set_subtitle_cache(key_gtxplus, new_text)
            elif lvl in ("tier3", "ai"):
                total = max(1, tier.get("total") or len(cues))
                if tier.get("llm_lines", 0) / total >= 0.8:
                    await set_subtitle_cache(key_llm, new_text)
                else:
                    await set_subtitle_cache(key_gtxplus, new_text)
    return new_text, tier


async def _translate_with_fallback(cues, src, tgt, requested_mode="gtx"):
    """Multi-tier translate dengan penanganan prioritas sesuai mode yang diminta:
    Mode AI:
      1. AI Fansub LLM (jika aktif)
      2. Fallback: Google Translate GTX+ (Smart Fansub & Scene Detection)
      3. Fallback: Google Translate GTX murni
    Mode GTX+ / AIGTX:
      1. Google Translate GTX+ (Smart Fansub & Scene Detection)
      2. Fallback: AI Fansub LLM (jika aktif)
      3. Fallback: Google Translate GTX murni
    Mode GTX:
      1. Google Translate GTX murni
      2. Fallback: Google Translate GTX+
      3. Fallback: AI Fansub LLM (jika aktif)
    Safety net: source original
    """
    from api.translate import call_openai_translate, call_gtx_translate
    last_err = ""

    if requested_mode == "ai":
        # 1. Coba AI Fansub jika ada API key atau LLM lokal
        if await _llm_enabled():
            apikey = await get_setting("translate_apikey", "")
            model = await get_setting("translate_model", "gemini-2.0-flash")
            apiurl = await get_setting("translate_apiurl", "https://generativelanguage.googleapis.com/v1beta/openai")
            try:
                translated, stats = await call_openai_translate(cues, src, tgt, apikey, model, apiurl)
                return {"cues": translated, "level": "tier3", "engine": "ai", **stats}
            except Exception as e:
                last_err = f"AI LLM error: {e}"
                print(f"[TRANSLATE AI LLM ERROR] {e}")
        else:
            last_err = "AI LLM belum disetel (masukkan API key di pengaturan)"
            print(f"[TRANSLATE AI LLM] {last_err}")

        # Fallback ke Google GTX+
        try:
            translated = await call_gtx_translate(cues, src, tgt, mode="gtx+")
            return {"cues": translated, "level": "tier2", "engine": "gtx+", "error": last_err}
        except Exception as e:
            last_err = f"{last_err} | GTX+ error: {e}"
            print(f"[TRANSLATE GTX+ ERROR] {e}")

        # Fallback ke Google GTX
        try:
            translated = await call_gtx_translate(cues, src, tgt, mode="gtx")
            return {"cues": translated, "level": "tier1", "engine": "gtx", "error": last_err}
        except Exception as e:
            last_err = f"{last_err} | GTX error: {e}"
            print(f"[TRANSLATE GTX ERROR] {e}")

    elif requested_mode in ("gtx+", "aigtx"):
        # 1. Coba Google GTX+ (Smart Fansub & Scene Detection)
        try:
            translated = await call_gtx_translate(cues, src, tgt, mode="gtx+")
            return {"cues": translated, "level": "tier2", "engine": "gtx+"}
        except Exception as e:
            last_err = f"GTX+ error: {e}"
            print(f"[TRANSLATE GTX+ ERROR] {e}")

        # 2. Coba AI jika aktif
        if await _llm_enabled():
            apikey = await get_setting("translate_apikey", "")
            model = await get_setting("translate_model", "gemini-2.0-flash")
            apiurl = await get_setting("translate_apiurl", "https://generativelanguage.googleapis.com/v1beta/openai")
            try:
                translated, stats = await call_openai_translate(cues, src, tgt, apikey, model, apiurl)
                return {"cues": translated, "level": "tier3", "engine": "ai", **stats}
            except Exception as e:
                last_err = f"{last_err} | AI LLM error: {e}"
                print(f"[TRANSLATE AI LLM ERROR] {e}")

        # 3. Fallback ke Google GTX
        try:
            translated = await call_gtx_translate(cues, src, tgt, mode="gtx")
            return {"cues": translated, "level": "tier1", "engine": "gtx", "error": last_err}
        except Exception as e:
            last_err = f"{last_err} | GTX error: {e}"
            print(f"[TRANSLATE GTX ERROR] {e}")

    else:
        # 1. Coba Google GTX murni
        try:
            translated = await call_gtx_translate(cues, src, tgt, mode="gtx")
            return {"cues": translated, "level": "tier1", "engine": "gtx"}
        except Exception as e:
            last_err = f"Google Translate error: {e}"
            print(f"[TRANSLATE GOOGLE GTX ERROR] {e}")

        # 2. Fallback ke Google GTX+
        try:
            translated = await call_gtx_translate(cues, src, tgt, mode="gtx+")
            return {"cues": translated, "level": "tier2", "engine": "gtx+", "error": last_err}
        except Exception as e:
            last_err = f"{last_err} | GTX+ error: {e}"
            print(f"[TRANSLATE GTX+ ERROR] {e}")

        # 3. Coba AI jika aktif
        if await _llm_enabled():
            apikey = await get_setting("translate_apikey", "")
            model = await get_setting("translate_model", "gemini-2.0-flash")
            apiurl = await get_setting("translate_apiurl", "https://generativelanguage.googleapis.com/v1beta/openai")
            try:
                translated, stats = await call_openai_translate(cues, src, tgt, apikey, model, apiurl)
                return {"cues": translated, "level": "tier3", "engine": "ai", **stats}
            except Exception as e:
                last_err = f"{last_err} | AI LLM error: {e}"
                print(f"[TRANSLATE AI LLM ERROR] {e}")

    # Return cues asli jika semua penerjemah gagal
    return {"cues": cues, "level": "source", "error": last_err}

def find_mpv_binary():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(root_dir, "bin", "mpv.exe"),
        os.path.join(root_dir, "bin", "mpv"),
        os.path.join(root_dir, "mpv", "mpv.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    import shutil
    return shutil.which("mpv.exe" if sys.platform == "win32" else "mpv")

@app.post("/api/play-mpv")
async def play_mpv(body: dict = None):
    body = body or {}
    slug, ep, mode = body.get("slug", ""), int(body.get("ep", 1)), body.get("mode", "sub")
    quality = body.get("quality", await get_setting("quality", "best"))
    # Opsional: user pilih subtitle spesifik via UI ("sub_url" berisi URL track
    # yang aktif). Backend tetap attach seluruh subtitles[] ke MPV (--sub-file
    # bisa lebih dari satu) supaya user bisa cycle lewat tombol 'j'.
    preferred_sub_url = body.get("sub_url") or ""
    try:
        mpv_bin = find_mpv_binary()
        if not mpv_bin:
            return fail("mpv tidak ditemukan. Taruh mpv.exe di folder 'bin/' atau install mpv ke sistem.")

        loop = asyncio.get_running_loop()
        hit = await get_episode_cache(slug, ep, mode)
        if not hit and mode == "sub":
            hit = await get_episode_cache(slug, ep, "dub")
        elif not hit and mode == "dub":
            hit = await get_episode_cache(slug, ep, "sub")
        if hit:
            got = dict(hit)
        else:
            maps = await loop.run_in_executor(None, lambda: hi.hianime_episodes(slug))
            got = await loop.run_in_executor(None, lambda: hi.hianime_m3u8(maps, ep, mode, slug))
        picked = hi.select_quality(got["variants"], quality)
        m_url = got.get("master", "")
        stream_target = m_url if (m_url and (".m3u8" in m_url or "/hls" in m_url)) else picked["url"]
        cmd = [mpv_bin, f"--referer={got.get('referer','')}", stream_target]
        # Kumpulkan subtitle files. Prioritas:
        #   1) preferred_sub_url (kalau client pilih spesifik), atau default 'sub'
        #   2) SELURUH subtitles[] dari cache/result, agar semua track terpasang
        #      dan user bisa cycle via 'j' di MPV.
        # File VTT didownload ke tempdir (mpv butuh path lokal). File yang gagal
        # didownload di-skip agar tidak menggagalkan playback.
        # Catatan: subs_all mengandung tracks unik saja — kalau 'sub' (default)
        # sudah ada di subtitles[] dengan URL sama, skip supaya tidak duplikat.
        subs_all = []
        seen_urls = set()
        for s in (got.get("subtitles") or []):
            url = (s or {}).get("url")
            if url and url not in seen_urls:
                subs_all.append(s)
                seen_urls.add(url)
        if preferred_sub_url and preferred_sub_url not in seen_urls:
            subs_all.append({"label": "Selected", "url": preferred_sub_url,
                             "lang": "", "default": False})
            seen_urls.add(preferred_sub_url)
        elif got.get("sub") and got["sub"] not in seen_urls:
            # Pakai default 'sub' hanya kalau belum ada di subtitles[].
            subs_all.append({"label": got.get("sub_lang") or "Default",
                             "url": got["sub"], "lang": "", "default": True})
            seen_urls.add(got["sub"])

        # Helper download async; return None kalau gagal (skip track).
        async def _download_sub(url):
            try:
                from api.hianime import _host_from, _BLOCKED_DPI_HOSTS
                h = _host_from(url)
                if h in _BLOCKED_DPI_HOSTS:
                    from api.desync import tls_desync_request
                    loop = asyncio.get_running_loop()
                    raw = await loop.run_in_executor(None, lambda: tls_desync_request(url, headers={"Referer": got.get("referer", "")}))
                    text = raw.decode("utf-8", errors="replace")
                else:
                    async with httpx.AsyncClient(timeout=15) as c:
                        sr = await c.get(url, headers={"User-Agent": HI_UA,
                                                        "Referer": got.get("referer", "")})
                        if sr.status_code != 200 or not sr.text:
                            return None
                        text = sr.text

                if not text:
                    return None
                fp = os.path.join(tempfile.gettempdir(),
                                  f"{slug}-ep{ep}-{abs(hash(url)) % 10**8}.vtt")
                open(fp, "w").write(text)
                return fp
            except Exception:
                return None

        downloaded = []
        for s in subs_all:
            url = (s or {}).get("url")
            if not url:
                continue
            fp = await _download_sub(url)
            if fp:
                downloaded.append(fp)

        # Masukkan --sub-file sebelum URL. mpv izinkan multiple --sub-file.
        # Sisip di posisi 2 (setelah mpv_bin + --referer=) agar tidak geser posisi URL.
        for fp in downloaded:
            cmd.insert(2, f"--sub-file={fp}")

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
        await add_history(slug, body.get("title", slug), ep, mode)
        return ok({"cmd": cmd, "picked": picked, "subs_attached": len(downloaded)})
    except Exception as e:
        return fail(str(e))

@app.post("/api/shutdown")
async def shutdown():
    def _do_exit():
        import time
        time.sleep(0.3)
        os._exit(0)
    import threading
    threading.Thread(target=_do_exit, daemon=True).start()
    return ok({"message": "Server shutting down..."})

@app.get("/api/history")
async def history():
    return ok(await get_history())

@app.post("/api/history")
async def save_hist(body: dict = None):
    body = body or {}
    await add_history(
        body.get("slug", ""),
        body.get("title", ""),
        int(body.get("episode", 1)),
        body.get("mode", "sub"),
        int(body.get("progress", 0)),
        body.get("poster", ""),
        body.get("type", "")
    )
    return ok(True)

@app.delete("/api/history")
async def del_hist():
    await clear_history()
    return ok(True)

@app.get("/api/settings")
async def get_set():
    return ok({
        "quality": await get_setting("quality", "best"),
        "mode": await get_setting("mode", "sub"),
        "player": await get_setting("player", "browser"),
        "preferred_source": await get_setting("preferred_source", "hianime"),
        # Preferensi bahasa subtitle user. Default "English" karena sebagian besar
        # sumber (Megaplay, ZokoAnime) punya English sebagai track default. Kalau
        # user pernah pilih bahasa lain, disimpan di sini dan dipakai frontend
        # untuk auto-select track di episode berikutnya.
        "sub_lang": await get_setting("sub_lang", "English"),
        # Translate API (opsional). User isi via settings panel. Fallback ke
        # MyMemory kalau kosong. translate_apikey tidak pernah di-log.
        "translate_apikey": await get_setting("translate_apikey", ""),
        "translate_model": await get_setting("translate_model", "gemini-2.0-flash"),
        "translate_apiurl": await get_setting("translate_apiurl", "https://generativelanguage.googleapis.com/v1beta/openai"),
    })

@app.post("/api/settings")
async def set_set(body: dict = None):
    body = body or {}
    # Otomatis sesuaikan model & apiurl berdasarkan format apikey dari pengguna jika tidak dispesifikasikan eksplisit
    if "translate_apikey" in body:
        val = body["translate_apikey"]
        if isinstance(val, str):
            val = val.strip().strip("\"'").strip()
            body["translate_apikey"] = val
            if val:
                from api.translate import detect_provider_from_key
                _, inferred_model, inferred_url = detect_provider_from_key(val)
                if not body.get("translate_model"):
                    body["translate_model"] = inferred_model
                if not body.get("translate_apiurl"):
                    body["translate_apiurl"] = inferred_url

    for k in ("quality", "mode", "player", "sub_lang", "preferred_source",
              "translate_apikey", "translate_model", "translate_apiurl"):
        if k in body:
            await set_setting(k, body[k])
    return await get_set()

@app.get("/api/translate/logs")
async def get_translate_logs_api():
    """Mengambil riwayat log aktivitas translasi subtitle terbaru."""
    from api.translate import get_translate_logs
    return {"success": True, "data": {"logs": get_translate_logs()}}

if os.path.isdir(os.path.join(frontend_dir, "js")):
    app.mount("/js", StaticFiles(directory=os.path.join(frontend_dir, "js")), name="js")
if os.path.isdir(os.path.join(frontend_dir, "css")):
    app.mount("/css", StaticFiles(directory=os.path.join(frontend_dir, "css")), name="css")
if os.path.isdir(os.path.join(frontend_dir, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")

@app.get("/")
async def root():
    idx_path = os.path.join(frontend_dir, "index.html")
    if os.path.isfile(idx_path):
        return FileResponse(idx_path, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        })
    return ok({"status": "running", "app": "Tatap Native Android Backend"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=APP_HOST, port=APP_PORT, loop="asyncio", http="h11")
