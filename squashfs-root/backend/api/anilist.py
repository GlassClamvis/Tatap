"""Ambil daftar anime per-season dari AniList GraphQL."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import HI_UA
import httpx

ANILIST_URL = "https://graphql.anilist.co"
UA = HI_UA

QUERY = """
query ($season: MediaSeason, $year: Int, $page: Int, $perPage: Int, $statusIn: [MediaStatus]) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { total perPage currentPage lastPage hasNextPage }
    media(season: $season, seasonYear: $year, status_in: $statusIn, type: ANIME, sort: POPULARITY_DESC) {
      id
      status
      title { romaji english }
      format
      episodes
      duration
      averageScore
      season
      seasonYear
      coverImage { large medium }
      siteUrl
    }
  }
}
"""

def current_season():
    """Return (year, season_name) untuk bulan hari ini."""
    import datetime as _dt
    m = _dt.date.today().month
    name = "winter" if m in (1,2,3) else "spring" if m in (4,5,6) \
          else "summer" if m in (7,8,9) else "fall"
    return _dt.date.today().year, name

def prev_season(name, year):
    order = ["winter", "spring", "summer", "fall"]
    idx = order.index(name)
    if idx == 0:
        return year - 1, "fall"
    return year, order[idx - 1]

_al_client = None

def _get_al_client():
    global _al_client
    if _al_client is None:
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=60.0)
        _al_client = httpx.Client(
            timeout=httpx.Timeout(12.0, connect=5.0),
            limits=limits,
            headers={"Content-Type": "application/json", "User-Agent": UA}
        )
    return _al_client

_season_last_page_cache = {}

def get_season_last_page(season_name, season_year, status_in=None):
    """Cari halaman terakhir dari anime seasonal secara akurat via binary search probe."""
    key = (str(season_name).upper(), int(season_year), tuple(status_in or []))
    if key in _season_last_page_cache:
        return _season_last_page_cache[key]

    c = _get_al_client()
    probe_query = """query($s: MediaSeason, $y: Int, $p: Int, $st: [MediaStatus]) {
      Page(page: $p, perPage: 25) {
        pageInfo { hasNextPage }
        media(season: $s, seasonYear: $y, status_in: $st, type: ANIME) { id }
      }
    }"""
    low = 1
    high = 12
    last_found = 1
    while low <= high:
        mid = (low + high) // 2
        try:
            r = c.post(ANILIST_URL, json={
                "query": probe_query,
                "variables": {
                    "s": str(season_name).upper(),
                    "y": int(season_year),
                    "p": mid,
                    "st": status_in
                }
            }, timeout=6.0)
            if r.status_code != 200:
                break
            d = r.json().get("data", {}).get("Page", {})
            media = d.get("media", [])
            has_next = d.get("pageInfo", {}).get("hasNextPage")
            if media:
                last_found = max(last_found, mid)
                if has_next:
                    low = mid + 1
                else:
                    last_found = mid
                    break
            else:
                high = mid - 1
        except Exception:
            break

    _season_last_page_cache[key] = max(1, last_found)
    return _season_last_page_cache[key]

def season_page(name, year, page=1, per_page=25, status_in=None):
    """Fetch satu halaman AniList untuk season/year tertentu. Return {pageInfo, media:[]}."""
    try:
        c = _get_al_client()
        variables = {
            "season": name.upper(),
            "year": year,
            "page": page,
            "perPage": per_page
        }
        if status_in:
            variables["statusIn"] = status_in
        r = c.post(ANILIST_URL, json={
            "query": QUERY,
            "variables": variables
        })
        if r.status_code != 200:
            return {"pageInfo": {"total": 0, "perPage": per_page, "currentPage": page,
                                 "lastPage": 1, "hasNextPage": False}, "media": []}
        d = r.json().get("data", {}).get("Page", {})
        d.setdefault("pageInfo", {})
        d.setdefault("media", [])
        items = d.get("media") or []
        pi = d.get("pageInfo") or {}
        has_next = bool(pi.get("hasNextPage")) and len(items) >= per_page
        pi["hasNextPage"] = has_next
        pi["perPage"] = per_page
        pi["currentPage"] = page

        if not has_next:
            pi["lastPage"] = page
            cache_key = (str(name).upper(), int(year), tuple(status_in or []))
            _season_last_page_cache[cache_key] = max(_season_last_page_cache.get(cache_key, 1), page)
        else:
            try:
                exact_last = get_season_last_page(name, year, status_in)
                pi["lastPage"] = max(page + 1, exact_last)
            except Exception:
                pi["lastPage"] = max(page + 1, 4)
        d["pageInfo"] = pi
        return d
    except Exception:
        return {"pageInfo": {"total": 0, "perPage": per_page, "currentPage": page,
                             "lastPage": 1, "hasNextPage": False}, "media": []}


SCHEDULE_QUERY = """
query ($now: Int, $end: Int, $perPage: Int) {
  Page(perPage: $perPage) {
    airingSchedules(airingAt_greater: $now, airingAt_lesser: $end, sort: TIME) {
      id airingAt episode
      media {
        id title { romaji english }
        season seasonYear format
        coverImage { large medium }
      }
    }
  }
}
"""



SCHEDULE_PAGED_QUERY = """
query GetSchedule($page: Int, $now: Int, $end: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { hasNextPage currentPage }
    airingSchedules(airingAt_greater: $now, airingAt_lesser: $end, sort: TIME) {
      id airingAt episode
      media {
        id title { romaji english }
        season seasonYear format
        genres averageScore
        coverImage { large medium }
      }
    }
  }
}
"""

def anilist_schedules(now_ts, end_ts, per_page=50):
    """Episode yang tayang antara now_ts..end_ts (unix detik). Return list schedule.
    Longgar: anime apapun, tidak difilter by season. Caller yang filter matched."""
    try:
        c = _get_al_client()
        r = c.post(ANILIST_URL, json={
            "query": SCHEDULE_QUERY,
            "variables": {"now": now_ts, "end": end_ts, "perPage": per_page}
        })
        if r.status_code != 200:
            return []
        return r.json().get("data", {}).get("Page", {}).get("airingSchedules", []) or []
    except Exception:
        return []

def anilist_schedules_range(start_ts: int, end_ts: int, max_pages: int = 3):
    """Episode yang tayang dalam rentang waktu (start_ts..end_ts) dengan pagination."""
    all_schedules = []
    c = _get_al_client()
    for page in range(1, max_pages + 1):
        try:
            r = c.post(ANILIST_URL, json={
                "query": SCHEDULE_PAGED_QUERY,
                "variables": {"page": page, "now": start_ts, "end": end_ts, "perPage": 50}
            })
            if r.status_code != 200:
                break
            d = r.json().get("data", {}).get("Page", {})
            schedules = d.get("airingSchedules") or []
            all_schedules.extend(schedules)
            if not d.get("pageInfo", {}).get("hasNextPage"):
                break
        except Exception:
            break
    return all_schedules


RELATIONS_QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME) {
    id
    title { romaji english }
    format
    seasonYear
    relations {
      edges {
        relationType
        node {
          id
          title { romaji english }
          format
          seasonYear
          status
          coverImage { medium large }
        }
      }
    }
  }
}
"""


MEDIA_BY_ID_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji english }
    format
    seasonYear
    status
    coverImage { medium large }
    relations {
      edges {
        relationType
        node {
          id
          title { romaji english }
          format
          seasonYear
          status
          coverImage { medium large }
        }
      }
    }
  }
}
"""


def anime_relations(search_query: str):
    """Ambil relasi franchise anime (Prequel, Sequel, Parent, Side Story, dll) dari AniList,
    termasuk menelusuri rantai prekuel ke belakang untuk menemukan karya awal (Season 1)."""
    if not search_query or not search_query.strip():
        return []
    try:
        c = _get_al_client()
        r = c.post(ANILIST_URL, json={
            "query": RELATIONS_QUERY,
            "variables": {"search": search_query.strip()}
        })
        if r.status_code != 200:
            return []
        data = r.json().get("data", {}).get("Media", {})
        if not data or not data.get("id"):
            return []

        current_id = data.get("id")
        edges = data.get("relations", {}).get("edges", []) or []
        out = []
        seen_ids = {current_id}

        # 1. Kumpulkan relasi langsung (1-hop)
        direct_prequel_node = None
        for edge in edges:
            rel = edge.get("relationType", "")
            node = edge.get("node", {})
            n_id = node.get("id")
            fmt = (node.get("format") or "").upper()
            if rel in ("PREQUEL", "SEQUEL", "PARENT", "SIDE_STORY", "ALTERNATIVE", "SUMMARY") and fmt in ("TV", "MOVIE", "OVA", "ONA", "SPECIAL"):
                if n_id and n_id not in seen_ids:
                    seen_ids.add(n_id)
                    t_obj = node.get("title", {}) or {}
                    t_eng = t_obj.get("english") or ""
                    t_rom = t_obj.get("romaji") or ""
                    title = t_eng if t_eng else t_rom
                    img = (node.get("coverImage") or {}).get("medium") or ""
                    entry = {
                        "id": n_id,
                        "relation": rel,
                        "format": fmt,
                        "title": title,
                        "title_romaji": t_rom,
                        "year": node.get("seasonYear"),
                        "status": node.get("status"),
                        "poster": img
                    }
                    out.append(entry)
                    if rel in ("PREQUEL", "PARENT") and direct_prequel_node is None:
                        direct_prequel_node = node

        # 2. Telusuri rantai prekuel ke belakang (hingga 5 langkah) untuk menemukan Season 1 / Origin
        curr_prequel = direct_prequel_node
        deepest_prequel = None
        for _ in range(5):
            if not curr_prequel or not curr_prequel.get("id"):
                break
            # Query node prekuel ini untuk melihat prekuel sebelumnya
            r_prev = c.post(ANILIST_URL, json={
                "query": MEDIA_BY_ID_QUERY,
                "variables": {"id": curr_prequel.get("id")}
            })
            if r_prev.status_code != 200:
                break
            prev_data = r_prev.json().get("data", {}).get("Media", {})
            prev_edges = prev_data.get("relations", {}).get("edges", []) or []

            next_prequel = None
            for e in prev_edges:
                p_rel = e.get("relationType", "")
                p_node = e.get("node", {})
                p_id = p_node.get("id")
                p_fmt = (p_node.get("format") or "").upper()
                if p_rel in ("PREQUEL", "PARENT") and p_id not in seen_ids and p_fmt in ("TV", "MOVIE", "OVA", "ONA", "SPECIAL"):
                    seen_ids.add(p_id)
                    p_t_obj = p_node.get("title", {}) or {}
                    p_t_eng = p_t_obj.get("english") or ""
                    p_t_rom = p_t_obj.get("romaji") or ""
                    p_title = p_t_eng if p_t_eng else p_t_rom
                    p_img = (p_node.get("coverImage") or {}).get("medium") or ""
                    p_entry = {
                        "id": p_id,
                        "relation": "PREQUEL",
                        "format": p_fmt,
                        "title": p_title,
                        "title_romaji": p_t_rom,
                        "year": p_node.get("seasonYear"),
                        "status": p_node.get("status"),
                        "poster": p_img
                    }
                    out.append(p_entry)
                    next_prequel = p_node
                    deepest_prequel = p_entry
                    break
            curr_prequel = next_prequel

        # Jika ditemukan prekuel paling awal (Season 1 / Origin), tandai secara eksplisit
        if deepest_prequel:
            deepest_prequel["is_origin"] = True

        return out
    except Exception:
        return []


