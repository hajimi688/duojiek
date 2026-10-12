#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
@header({
  searchable: 1,
  filterable: 1,
  quickSearch: 1,
  title: '番茄酱',
  lang: 'hipy'
})
"""

import base64, hashlib, hmac, json, re, time, uuid, urllib.parse
import requests
from base.spider import Spider

class Spider(Spider):
    name = "番茄酱"
    host = "https://fanqe.app"

    APP_VERSION = "1.1.23"
    APP_VERSION_CODE = "101"

    MEDIA_UA = (
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    )
    MW_UA = (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )

    MW_KEY = "cb808529bae6b6be45ecfab29a4889bc"
    MW_HOSTS = ("https://m.ksnnhbj.com", "https://www.ksnnhbj.com")
    MW_REFERER = "https://www.ksnnhbj.com"
    MW_PATH = "/api/mw-movie/anonymous/v2/video/episode/url"

    ETH_PARSER = "http://202.189.6.83:12991/xx/bt.php?url="

    STATION_LINES = (
        ("dsx", "番茄蓝光"),
        ("yzx", "云帧享"),
        ("yunsou", "金牌"),
    )

    VIRTUAL_RE = re.compile(r"fanqiecn\.com/jx/|sj\.fanqiecn\.com/", re.I)

    REFERER_MAP = (
        ("meilinvps.com", "https://m3u8.meilinvps.com/"),
        ("cmecloud.cn", "https://m3u8.meilinvps.com/"),
    )

    def init(self, extend=""):
        self.api = self.host + "/request/"
        self.headers = {
            "User-Agent": "Ktor client",
            "Accept": "application/json",
            "X-App-Platform": "android",
            "X-App-Version": self.APP_VERSION,
            "X-App-Version-Code": self.APP_VERSION_CODE,
        }
        self.install_id = None
        self.session_id = uuid.uuid4().hex
        self.device_id = str(uuid.uuid4())
        self.station = True
        self.session = requests.Session()
        self.session.proxies = {}

        if isinstance(extend, str) and extend:
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}
        if isinstance(extend, dict):
            if extend.get("install_id"):
                self.install_id = str(extend["install_id"])
            if extend.get("device_id"):
                self.device_id = str(extend["device_id"])
            if extend.get("version"):
                self.headers["X-App-Version"] = str(extend["version"])
            if extend.get("version_code"):
                self.headers["X-App-Version-Code"] = str(extend["version_code"])
            if "station" in extend:
                self.station = str(extend["station"]) in ("1", "true", "yes", "on")

    def getName(self):
        return self.name

    def _headers(self, url, method="GET", body=""):
        if not self.install_id:
            self.install_id = uuid.uuid4().hex
        u = urllib.parse.urlparse(url)

        p = u.path
        for pre in ("/request/v1/", "/request/", "/v1/"):
            if p.startswith(pre):
                p = p[len(pre) :]
                break
        p = p.rstrip("/")
        p = "/".join(x for x in p.split("/") if x)
        p = "/" + p if p else "/"

        q = {}
        if u.query:
            for pr in u.query.split("&"):
                if "=" in pr:
                    k, v = pr.split("=", 1)
                    q[k] = v
                else:
                    q[pr] = ""
        qstr = "&".join("%s=%s" % (k, q[k]) for k in sorted(q))

        ts = str(int(time.time()))
        nonce = uuid.uuid4().hex
        body_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        msg = "\n".join([method, p, qstr, body_sha, ts, nonce, self.install_id])
        sig = hmac.new(
            b"Rg0qTuu2BltwOIdVnzNVJy9sCbiOD9P90uO0aDDbGa4",
            msg.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        hd = dict(self.headers)
        hd.update(
            {
                "X-Install-Id": self.install_id,
                "X-Request-Timestamp": ts,
                "X-Request-Nonce": nonce,
                "X-Request-Signature": sig,
            }
        )
        return hd

    def _req(self, path, params=None, method="GET", body="", timeout=(4, 8), retry=0):
        if re.match(r"^https?://", str(path), re.I):
            url = str(path)
        else:
            url = self.api + path

        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

        for _ in range(retry + 1):
            hd = self._headers(url, method, body)
            try:
                if method == "POST":
                    r = self.session.post(url, headers=hd, data=body, timeout=timeout)
                else:
                    r = self.session.get(url, headers=hd, timeout=timeout)
                r.raise_for_status()
                j = r.json()
                if j.get("code") in (1, 200):
                    data = j.get("data")
                    if data is None:
                        return j
                    if isinstance(data, str):
                        try:
                            return json.loads(data)
                        except Exception:
                            return {"data": data}
                    return data
                return {}
            except Exception:
                continue
        return {}

    def _home_raw(self, timeout=(2, 5)):
        now = time.time()
        cached = getattr(self, "_home_cache", None)
        if cached and now - cached[0] < 120:
            return cached[1]
        data = self._req("home/content", {"id": 1}, timeout=timeout)
        if data:
            self._home_cache = (now, data)
        return data

    @staticmethod
    def _sections(home):
        items = []
        seen = set()
        for section in ("home_hot", "home_latest_movie", "home_latest_tv"):
            for v in (home or {}).get(section) or []:
                if not isinstance(v, dict):
                    continue
                vid = str(v.get("vod_id", ""))
                if vid and vid not in seen:
                    seen.add(vid)
                    items.append(v)
        return items

    def homeContent(self, filter):
        cats = self._req(
            "home/categories",
            {"page": 1, "page_size": 100, "status": -1},
            timeout=(2.5, 4),
            retry=1,
        )
        classes = []
        filters_map = {}
        if isinstance(cats, list):
            for c in cats:
                if not isinstance(c, dict):
                    continue
                cid = c.get("id") or c.get("cate")
                if cid is None:
                    continue
                tid = str(cid)
                fdefs = self._build_filters(c)
                cls = {"type_id": tid, "type_name": c.get("title", "")}

                if fdefs:
                    cls["filter"] = fdefs
                    filters_map[tid] = fdefs
                classes.append(cls)

        items = [self._item(v) for v in self._sections(self._home_raw((1.5, 3)))]
        return {"class": classes, "list": items, "filters": filters_map}

    def homeVideoContent(self):
        items = [self._item(v) for v in self._sections(self._home_raw((4, 8)))]
        return {"list": items}

    def _build_filters(self, c):
        ext = c.get("extend") or {}
        if not isinstance(ext, dict):
            return []
        fdefs = []
        types = [
            t
            for t in (ext.get("types") or [])
            if isinstance(t, dict) and t.get("type_name")
        ]
        if types:
            fdefs.append(
                {
                    "key": "class",
                    "name": "类型",
                    "value": [self._filter_item(t["type_name"]) for t in types],
                }
            )
        for key, name in (("area", "地区"), ("lang", "语言"), ("year", "年份")):
            vals = [str(x) for x in (ext.get(key + "_list") or []) if str(x)]
            if vals:
                fdefs.append(
                    {
                        "key": key,
                        "name": name,
                        "value": [self._filter_item(v) for v in vals],
                    }
                )
        return fdefs

    @staticmethod
    def _filter_item(name):
        s = str(name)
        return {"n": s, "v": s, "type_id": s, "type_name": s}

    def categoryContent(self, tid, pg, filter, extend):
        tid = str(tid)
        pg = int(pg) if str(pg).isdigit() else 1
        params = {
            "type": tid,
            "page": pg,
            "limit": 21,
            "order": "desc",
            "by": "recommend",
            "session_id": self.session_id,
        }

        if "|" in tid:
            base_tid, sub = tid.split("|", 1)
            params["type"] = base_tid
            if sub not in ("", "0"):
                params["class"] = sub

        for key in ("class", "area", "lang", "year"):
            val = self._filter_val((extend or {}).get(key))
            if val and val not in ("0", "全部", "不限"):
                params[key] = val

        data = self._req("catalog/content", params)
        items = [self._item(v) for v in data.get("data") or [] if isinstance(v, dict)]
        return {
            "page": pg,
            "pagecount": int(data.get("last_page") or 1),
            "limit": int(data.get("per_page") or 21),
            "total": int(data.get("total") or len(items)),
            "list": items,
        }

    @staticmethod
    def _filter_val(v):
        if v is None:
            return ""
        if isinstance(v, dict):
            v = v.get("v") or v.get("n") or v.get("type_name") or v.get("type_id") or ""
        return str(v)

    def searchContent(self, key, quick, pg=1):
        pg = int(pg) if str(pg).isdigit() else 1
        data = self._req("content/search", {"wd": key, "page": pg, "pageSize": 20})
        items = [self._item(v) for v in data.get("data") or [] if isinstance(v, dict)]
        return {
            "page": pg,
            "pagecount": int(data.get("last_page") or 1),
            "limit": int(data.get("per_page") or 20),
            "total": int(data.get("total") or len(items)),
            "list": items,
        }

    def _line_name(self, show, frm=""):
        s = (show or "").strip()
        s = re.sub(r"【?限时开放】?$", "", s).strip()
        s = re.sub(r"\s+", "", s)
        if s in ("星4K 蓝光4K", "星4K蓝光4K"):
            return "星4K"
        if s in ("星4K i4K", "星4Ki4K"):
            return "云4K"
        return s or frm

    @staticmethod
    def _pack(frm, show, mode, url, vod_id=""):
        d = {"f": frm, "s": show, "m": mode, "u": url}
        if vod_id:
            d["v"] = vod_id
        raw = json.dumps(d, ensure_ascii=False).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _unpack(pid):
        try:
            raw = base64.urlsafe_b64decode(
                str(pid) + "=" * (-len(str(pid)) % 4)
            ).decode("utf-8")
            d = json.loads(raw)
            return d if isinstance(d, dict) else None
        except Exception:
            return None

    @staticmethod
    def _unwrap(url):
        try:
            u = urllib.parse.urlparse(str(url))
            if "fanqiecn.com" in (u.netloc or "") and u.path.endswith("/r.m3u8"):
                q = urllib.parse.parse_qs(u.query)
                v = (q.get("v") or [""])[0]
                if re.match(r"^https?://", v, re.I):
                    return v
        except Exception:
            pass
        return ""

    def _line_mode(self, frm, url, ps):
        u = (url or "").strip()
        if ps == "2":
            return "jx"
        if u.startswith("ETH-"):
            return "eth"
        if re.match(r"^\d+\|\d+$", u):
            return "mw"
        if self.VIRTUAL_RE.search(u):
            return "resolve"
        if re.match(r"^https?://", u, re.I):
            return "direct"
        return "resolve"

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else ids
        v = self._req(
            "content/detail",
            {"id": str(vid), "__platform": "Android", "__ic": "XX"},
            retry=1,
        )
        if not v:
            return {"list": []}

        play_from = []
        play_url = []
        pl = v.get("vod_play_list") or []

        for item in pl:
            if not isinstance(item, dict):
                continue
            pi = item.get("player_info") or {}
            frm = pi.get("from") or ""
            show = pi.get("show") or frm
            ps = str(pi.get("ps") or "0")
            urls = item.get("urls") or []
            if not urls or not frm:
                continue

            sample = urls[0].get("url", "") if isinstance(urls[0], dict) else ""
            mode = self._line_mode(frm, sample, ps)
            disp = self._line_name(show, frm)
            segs = []

            for ep in urls:
                if not isinstance(ep, dict):
                    continue
                nm = str(ep.get("name", ""))
                u = str(ep.get("url", ""))
                if not u:
                    continue
                inner = self._unwrap(u)
                if inner:
                    segs.append("%s$%s" % (nm, self._pack(frm, show, "direct", inner)))
                else:
                    segs.append("%s$%s" % (nm, self._pack(frm, show, mode, u)))

            if segs and disp not in play_from:
                play_from.append(disp)
                play_url.append("#".join(segs))

        if self.station:
            self._append_station_lines(v, play_from, play_url)

        vod = self._item(v)
        vod["vod_play_from"] = "$$$".join(play_from)
        vod["vod_play_url"] = "$$$".join(play_url)
        return {"list": [vod]}

    def _append_station_lines(self, v, play_from, play_url):
        title = (v.get("vod_name") or "").strip()
        if not title:
            return
        deadline = time.time() + 8
        for line, disp in self.STATION_LINES:
            if time.time() > deadline:
                break
            if disp in play_from:
                continue
            try:
                s = self._req(
                    "station/jx/search",
                    {"line": line, "wd": title, "q": title},
                    timeout=(2, 5),
                )
                if not isinstance(s, dict):
                    continue
                hits = [
                    it
                    for it in (s.get("list") or [])
                    if isinstance(it, dict)
                    and title == (it.get("vod_name") or "").strip()
                ]
                if not hits:
                    hits = [
                        it
                        for it in (s.get("list") or [])
                        if isinstance(it, dict) and title in (it.get("vod_name") or "")
                    ]
                if not hits:
                    continue

                svid = str(hits[0].get("vod_id") or "")
                if not svid:
                    continue

                d = self._req(
                    "station/jx/detail",
                    {"line": line, "vod_id": svid, "id": svid},
                    timeout=(2, 5),
                )
                dl = d.get("list") if isinstance(d, dict) else None
                if not (isinstance(dl, list) and dl and isinstance(dl[0], dict)):
                    continue
                pu = dl[0].get("vod_play_url") or ""
                if not pu:
                    continue

                segs = []
                for ep in pu.split("#"):
                    if "$" not in ep:
                        continue
                    nm, eid = ep.split("$", 1)
                    eid = eid.strip()
                    if not eid:
                        continue
                    if line == "dsx":
                        mode, u, sv = "eth", eid, ""
                    elif line == "yunsou":
                        mode, u, sv = "mw", "%s|%s" % (svid, eid), ""
                    else:
                        mode, u, sv = "jx", eid, svid
                    segs.append("%s$%s" % (nm, self._pack(line, disp, mode, u, sv)))

                if segs:
                    play_from.append(disp)
                    play_url.append("#".join(segs))
            except Exception:
                continue

    def playerContent(self, flag, id, vipFlags):
        if id and "$" in str(id):
            id = str(id).split("$", 1)[1]

        info = self._unpack(id)
        if not info:
            u = str(id)
            if re.match(r"^https?://", u, re.I):
                return self._direct(u)
            return {"parse": 1, "jx": 1, "url": u, "header": {}}

        mode = info.get("m") or "resolve"
        u = info.get("u") or ""
        frm = info.get("f") or ""
        show = info.get("s") or frm

        try:
            if mode == "direct":
                return self._direct(u)
            if mode == "mw":
                return self._play_mw(u)
            if mode == "eth":
                return self._play_eth(u)
            if mode == "jx":
                return self._play_jx(frm, info.get("v") or "", u)
            return self._play_resolve(frm, show, u)
        except Exception:
            return {"parse": 1, "jx": 1, "url": u, "header": {}}

    def _media_header(self, extra=None):
        h = {"User-Agent": self.MEDIA_UA}
        if isinstance(extra, dict):
            for k, v in extra.items():
                if v:
                    h[k] = v
        return json.dumps(h)

    def _direct(self, url):
        hdr = {"User-Agent": self.MEDIA_UA}
        for host, ref in self.REFERER_MAP:
            if host in (url or ""):
                hdr["Referer"] = ref
                break
        return {"parse": 0, "jx": 0, "url": url, "header": json.dumps(hdr)}

    def _play_resolve(self, frm, show, url):
        data = self._req(
            "playback/resolve",
            {"key": frm, "label": show, "play_url": url, "player_from": frm},
            method="POST",
            retry=1,
            timeout=(4, 10),
        )
        u = data.get("url") if isinstance(data, dict) else ""
        if not u:
            if re.match(r"^https?://", str(url), re.I) and not self.VIRTUAL_RE.search(
                str(url)
            ):
                return self._direct(url)
            return {"parse": 1, "jx": 1, "url": "", "header": {}}

        hdr = {"User-Agent": self.MEDIA_UA}
        h = data.get("header")
        if isinstance(h, dict):
            for k, v in h.items():
                if v:
                    hdr[k] = v
        media = ((data.get("playback") or {}).get("media")) or {}
        ref = media.get("referer")
        if ref:
            hdr.setdefault("Referer", ref)
        else:
            for host, r2 in self.REFERER_MAP:
                if host in u:
                    hdr.setdefault("Referer", r2)
                    break
        return {"parse": 0, "jx": 0, "url": u, "header": json.dumps(hdr)}

    def _play_mw(self, token):
        if "|" not in str(token):
            return {"parse": 1, "jx": 1, "url": "", "header": {}}
        vid, nid = str(token).split("|", 1)
        vid, nid = vid.strip(), nid.strip()
        if not (vid and nid):
            return {"parse": 1, "jx": 1, "url": "", "header": {}}

        params = "clientType=1&id=%s&nid=%s" % (vid, nid)
        for host in self.MW_HOSTS:
            try:
                ts = str(int(time.time() * 1000))
                md5hex = hashlib.md5(
                    (params + "&key=" + self.MW_KEY + "&t=" + ts).encode("utf-8")
                ).hexdigest()
                sign = hashlib.sha1(md5hex.encode("utf-8")).hexdigest()
                hd = {
                    "User-Agent": self.MW_UA,
                    "Accept": "application/json, text/plain, */*",
                    "sign": sign,
                    "t": ts,
                    "deviceId": self.device_id,
                    "client-type": "1",
                    "Referer": "%s/vod/play/%s/1/%s" % (self.MW_REFERER, vid, nid),
                    "Origin": self.MW_REFERER,
                }
                r = self.session.get(
                    host + self.MW_PATH + "?" + params, headers=hd, timeout=(4, 12)
                )
                j = r.json()
                lst = ((j.get("data") or {}).get("list")) or []
                best = None
                for it in lst:
                    if not isinstance(it, dict) or not it.get("url"):
                        continue
                    if best is None or int(it.get("resolution") or 0) > int(
                        best.get("resolution") or 0
                    ):
                        best = it
                if best:
                    return self._direct(best["url"])
            except Exception:
                continue
        return {"parse": 1, "jx": 1, "url": "", "header": {}}

    def _play_eth(self, blob):
        try:
            url = self.ETH_PARSER + urllib.parse.quote(str(blob), safe="")
            r = self.session.get(
                url,
                headers={
                    "User-Agent": "Dart/3.13 (dart:io)",
                    "Accept": "application/json, */*",
                },
                timeout=(4, 15),
            )
            j = r.json()
            u = j.get("url") or ""
            if u:
                return self._direct(u)
        except Exception:
            pass
        return {"parse": 1, "jx": 1, "url": "", "header": {}}

    def _play_jx(self, line, vid, eid):
        ep = 1
        parts = str(eid).split(":")
        if len(parts) >= 2 and parts[1].isdigit():
            ep = int(parts[1]) + 1
        d = self._req(
            "station/jx/play",
            {"line": line, "vod_id": vid, "ep": ep, "url": eid},
            timeout=(4, 10),
        )
        u = d.get("url") if isinstance(d, dict) else ""
        if not u:
            return {"parse": 1, "jx": 1, "url": "", "header": {}}
        hdr = {"User-Agent": self.MEDIA_UA}
        h = d.get("header")
        if isinstance(h, dict):
            for k, v in h.items():
                if v:
                    hdr[k] = v
        for host, ref in self.REFERER_MAP:
            if host in u:
                hdr.setdefault("Referer", ref)
                break
        return {"parse": 0, "jx": 0, "url": u, "header": json.dumps(hdr)}

    def manualVideoCheck(self):
        pass

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(?:m3u8|mp4|flv|ts)(?:$|[?#])", url or "", re.I))

    def _item(self, v):
        return {
            "vod_id": str(v.get("vod_id", "")),
            "vod_name": v.get("vod_name", ""),
            "vod_pic": v.get("vod_pic", ""),
            "vod_remarks": v.get("vod_remarks", ""),
            "vod_blurb": v.get("vod_blurb", "") or "",
            "vod_tag": "file",
            "vod_actor": v.get("vod_actor", ""),
            "vod_director": v.get("vod_director", ""),
            "vod_year": v.get("vod_year", ""),
            "vod_area": v.get("vod_area", ""),
            "vod_score": str(v.get("vod_score", "")) if v.get("vod_score") else "",
            "vod_content": v.get("vod_blurb", ""),
            "type_name": v.get("vod_type_name", ""),
        }

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass
