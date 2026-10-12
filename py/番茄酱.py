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

番茄酱 TVBox Spider  (修复版)

数据源: https://fanqe.app/request/  (APK: app.fanqiejiang.birthday v1.1.23)
鉴权  : HMAC-SHA256 请求签名，密钥从 APK DEX 静态提取
        canonical = METHOD \\n path \\n querystring \\n sha256(body) \\n ts \\n nonce \\n install_id

【本次修复要点】
1. ★ playback/resolve 必须用 POST + JSON body，原脚本误用 GET + query，
   导致所有 sj.fanqiecn.com / fanqiecn.com/jx/r.m3u8 / JD-* 线路全部 401 signature mismatch。
2. 补齐 X-Device-ID、X-Session-Id 请求头（APK 中 X-Session-Id 被引用 78 次）。
3. 移除 station/jx/*（该接口实测 403，需登录账号，APK 内亦无此路径）。
4. 修正线路分流：ps=0 的 gulu:xxx / JD-xxx token 走服务端解析而非直接播放。
5. 集名美化（纯数字 -> 第N集），补 liveContent 电视直播。
6. detailContent 增强，支持 4 种真实线路形态：
   - 数字|数字      -> 芒果TV风格解析 (mw)
   - sj.fanqiecn.com -> playback/resolve
   - fanqiecn.com/jx/r.m3u8?v=<http> -> 直接播放
   - fanqiecn.com/jx/r.m3u8?v=gulu:.. -> playback/resolve
   - JD-* / ETH-*   -> playback/resolve / 第三方解析
"""

import base64, hashlib, hmac, json, re, time, uuid, urllib.parse
import requests
from base.spider import Spider


class Spider(Spider):
    name = "番茄酱"
    host = "https://fanqe.app"

    APP_VERSION = "1.1.23"
    APP_VERSION_CODE = "101"

    # HMAC 签名密钥（APK DEX 偏移 0x19f0ea 提取，实测有效）
    SIGN_KEY = b"Rg0qTuu2BltwOIdVnzNVJy9sCbiOD9P90uO0aDDbGa4"

    MEDIA_UA = (
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    )
    MW_UA = (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )

    # 芒果TV 风格接口（ps=0 且 url 形如 "id|nid"）
    MW_KEY = "cb808529bae6b6be45ecfab29a4889bc"
    MW_HOSTS = ("https://m.ksnnhbj.com", "https://www.ksnnhbj.com")
    MW_REFERER = "https://www.ksnnhbj.com"
    MW_PATH = "/api/mw-movie/anonymous/v2/video/episode/url"

    # 备用解析（ETH- 前缀线路）
    ETH_PARSERS = (
        "http://202.189.6.83:12991/xx/bt.php?url=",
        "http://191.101.132.92/xx/bt.php?url=",
        "http://202.189.6.83:12991/xx/bt2.php?url=",
    )

    VIRTUAL_RE = re.compile(r"fanqiecn\.com/jx/|sj\.fanqiecn\.com/", re.I)

    REFERER_MAP = (
        ("meilinvps.com", "https://m3u8.meilinvps.com/"),
        ("cmecloud.cn", "https://m3u8.meilinvps.com/"),
    )

    # ---------------------------------------------------------------- init
    def init(self, extend=""):
        self.api = self.host + "/request/"
        self.headers = {
            "User-Agent": "Ktor client",
            "Accept": "application/json",
            "X-App-Platform": "android",
            "X-App-Version": self.APP_VERSION,
            "X-App-Version-Code": self.APP_VERSION_CODE,
        }
        self.install_id = uuid.uuid4().hex
        self.session_id = uuid.uuid4().hex
        self.device_id = str(uuid.uuid4())
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
            if extend.get("host"):
                h = str(extend["host"]).rstrip("/")
                if h.startswith("http"):
                    self.host = h
                    self.api = h + "/request/"
            if extend.get("version"):
                self.headers["X-App-Version"] = str(extend["version"])
            if extend.get("version_code"):
                self.headers["X-App-Version-Code"] = str(extend["version_code"])

    def getName(self):
        return self.name

    # ------------------------------------------------------------- 签名
    def _headers(self, path, method="GET", qs="", body="", signed=True):
        """
        构造请求头。
        canonical message = METHOD \n path \n querystring \n body_sha256 \n ts \n nonce \n install_id
        其中 path 为去掉 /request/ 前缀后的归一化路径（以 / 开头）
        """
        hd = dict(self.headers)
        hd["X-Install-Id"] = self.install_id
        hd["X-Device-ID"] = self.device_id
        hd["X-Session-Id"] = self.session_id
        if not signed:
            return hd

        ts = str(int(time.time()))
        nonce = uuid.uuid4().hex
        body_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        msg = "\n".join([method, path, qs, body_sha, ts, nonce, self.install_id])
        sig = hmac.new(self.SIGN_KEY, msg.encode("utf-8"), hashlib.sha256).hexdigest()

        hd["X-Request-Timestamp"] = ts
        hd["X-Request-Nonce"] = nonce
        hd["X-Request-Signature"] = sig
        return hd

    # -------------------------------------------------------------- 请求
    @staticmethod
    def _canon_path(path):
        p = "/".join(x for x in str(path).split("/") if x)
        return "/" + p if p else "/"

    def _req(self, path, params=None, method="GET", body="", timeout=(4, 10), retry=1):
        """
        path  : 相对路径，如 "home/categories"
        params: dict -> 参与签名（按 key 排序后用 & 连接）
        method: GET / POST
        body  : POST 的 JSON 字符串（同时参与签名）
        """
        if re.match(r"^https?://", str(path), re.I):
            url = str(path)
            cp = self._canon_path(urllib.parse.urlparse(url).path)
        else:
            url = self.api + str(path).lstrip("/")
            cp = self._canon_path(path)

        qs = ""
        if params:
            items = [(str(k), str(params[k])) for k in sorted(params.keys())]
            qs = "&".join("%s=%s" % (k, v) for k, v in items)
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(items)
            cp = self._canon_path(path)

        last = {}
        for _ in range(retry + 1):
            hd = self._headers(cp, method, qs, body)
            try:
                if method == "POST":
                    hd["Content-Type"] = "application/json"
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
                last = j
            except Exception:
                continue
        return last if isinstance(last, dict) else {}

    # ------------------------------------------------------------ 首页
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
        items, seen = [], set()
        for section in ("home_hot", "home_latest_movie", "home_latest_tv",
                        "home_latest_anime", "home_latest_variety"):
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
            timeout=(2.5, 5),
            retry=1,
        )
        classes, filters_map = [], {}
        if isinstance(cats, list):
            for c in cats:
                if not isinstance(c, dict):
                    continue
                cid = c.get("id") or c.get("cate")
                if cid is None:
                    continue
                tid = str(cid)
                cls = {"type_id": tid, "type_name": c.get("title", "")}
                fdefs = self._build_filters(c)
                if fdefs:
                    cls["filter"] = fdefs
                    filters_map[tid] = fdefs
                classes.append(cls)

        items = [self._item(v) for v in self._sections(self._home_raw((1.5, 4)))]
        return {"class": classes, "list": items, "filters": filters_map}

    def homeVideoContent(self):
        items = [self._item(v) for v in self._sections(self._home_raw((4, 8)))]
        return {"list": items}

    def _build_filters(self, c):
        ext = c.get("extend") or {}
        if not isinstance(ext, dict):
            return []
        fdefs = []
        types = [t for t in (ext.get("types") or [])
                 if isinstance(t, dict) and t.get("type_name")]
        if types:
            fdefs.append({
                "key": "class",
                "name": "类型",
                "value": [self._filter_item(t["type_name"]) for t in types],
            })
        for key, name in (("area", "地区"), ("lang", "语言"), ("year", "年份")):
            vals = [str(x) for x in (ext.get(key + "_list") or []) if str(x)]
            if vals:
                fdefs.append({
                    "key": key,
                    "name": name,
                    "value": [self._filter_item(v) for v in vals],
                })
        return fdefs

    @staticmethod
    def _filter_item(name):
        s = str(name)
        return {"n": s, "v": s, "type_id": s, "type_name": s}

    @staticmethod
    def _filter_val(v):
        if v is None:
            return ""
        if isinstance(v, dict):
            v = v.get("v") or v.get("n") or v.get("type_name") or v.get("type_id") or ""
        return str(v)

    # ------------------------------------------------------------ 分类
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
        if not isinstance(data, dict):
            data = {}
        items = [self._item(v) for v in data.get("data") or [] if isinstance(v, dict)]
        return {
            "page": pg,
            "pagecount": int(data.get("last_page") or 1),
            "limit": int(data.get("per_page") or 21),
            "total": int(data.get("total") or len(items)),
            "list": items,
        }

    # ------------------------------------------------------------ 搜索
    def searchContent(self, key, quick, pg=1):
        pg = int(pg) if str(pg).isdigit() else 1
        data = self._req("content/search", {"wd": key, "page": pg, "pageSize": 20})
        if not isinstance(data, dict):
            data = {}
        items = [self._item(v) for v in data.get("data") or [] if isinstance(v, dict)]
        return {
            "page": pg,
            "pagecount": int(data.get("last_page") or 1),
            "limit": int(data.get("per_page") or 20),
            "total": int(data.get("total") or len(items)),
            "list": items,
        }

    # ------------------------------------------------------------ 线路名
    @staticmethod
    def _line_name(show, frm=""):
        s = (show or "").strip()
        s = re.sub(r"【?限时开放】?$", "", s).strip()
        s = re.sub(r"\s+", "", s)
        if s in ("星4K 蓝光4K", "星4K蓝光4K"):
            return "星4K"
        if s in ("星4K i4K", "星4Ki4K"):
            return "云4K"
        return s or frm

    # --------------------------------------------------------- 打包/解包
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
        """
        仅当 v= 后面是真正的 http(s) 地址时才解包；
        v=gulu:xxxx:0 这类虚拟 token 必须原样交给 playback/resolve。
        """
        try:
            u = urllib.parse.urlparse(str(url))
            if "fanqiecn.com" in (u.netloc or "") and u.path.endswith("/r.m3u8"):
                q = urllib.parse.parse_qs(u.query)
                v = (q.get("v") or [""])[0]
                # parse_qs 会自动 URL 解码
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
        # JD-xxxx / gulu-xxxx 等纯 token 也走服务端解析
        if re.match(r"^[A-Za-z][A-Za-z0-9]*-[0-9a-fA-F]{8,}$", u):
            return "resolve"
        if re.match(r"^https?://", u, re.I):
            return "direct"
        return "resolve"

    @staticmethod
    def _ep_name(nm, idx, total):
        """集名美化：纯数字 -> 第N集；否则原样"""
        s = str(nm or "").strip()
        if total > 1 and s.isdigit():
            return "第%s集" % s
        if not s:
            return "第%d集" % (idx + 1)
        return s

    # ------------------------------------------------------------ 详情
    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else ids
        v = self._req(
            "content/detail",
            {"id": str(vid), "__platform": "Android", "__ic": "XX"},
            timeout=(4, 12),
            retry=1,
        )
        if not isinstance(v, dict) or not v:
            return {"list": []}

        play_from, play_url = [], []
        for item in v.get("vod_play_list") or []:
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
            total = len(urls)
            for idx, ep in enumerate(urls):
                if not isinstance(ep, dict):
                    continue
                nm = self._ep_name(ep.get("name", ""), idx, total)
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

        vod = self._item(v)
        vod["vod_play_from"] = "$$$".join(play_from)
        vod["vod_play_url"] = "$$$".join(play_url)
        return {"list": [vod]}

    # ------------------------------------------------------------ 播放
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
                return self._play_resolve(frm, show, u)
            return self._play_resolve(frm, show, u)
        except Exception:
            return {"parse": 1, "jx": 1, "url": u, "header": {}}

    def _direct(self, url):
        hdr = {"User-Agent": self.MEDIA_UA}
        for host, ref in self.REFERER_MAP:
            if host in (url or ""):
                hdr["Referer"] = ref
                break
        return {"parse": 0, "jx": 0, "url": url, "header": json.dumps(hdr)}

    def _play_resolve(self, frm, show, url):
        """
        ★ 核心修复：playback/resolve 必须用 POST + JSON body，
          签名时 canonical path 不含查询串，body 的 sha256 参与签名。
        """
        body = json.dumps(
            {"key": frm, "label": show, "play_url": url, "player_from": frm},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        data = self._req(
            "playback/resolve",
            method="POST",
            body=body,
            timeout=(5, 20),
            retry=1,
        )
        u = ""
        hdr_extra = {}
        if isinstance(data, dict):
            u = data.get("url") or ""
            h = data.get("header")
            if isinstance(h, dict):
                hdr_extra = h
            # playback.media.referer 优先
            media = ((data.get("playback") or {}).get("media")) or {}
            if isinstance(media, dict) and media.get("referer"):
                hdr_extra.setdefault("Referer", media["referer"])

        if not u:
            # 保底：真实 http 地址且非虚拟中转 -> 直接播
            if re.match(r"^https?://", str(url), re.I) and not self.VIRTUAL_RE.search(str(url)):
                return self._direct(url)
            return {"parse": 1, "jx": 1, "url": "", "header": {}}

        hdr = {"User-Agent": self.MEDIA_UA}
        for k, v in hdr_extra.items():
            if v:
                hdr[k] = v
        if "Referer" not in hdr:
            for host, ref in self.REFERER_MAP:
                if host in u:
                    hdr["Referer"] = ref
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
        for base in self.ETH_PARSERS:
            try:
                url = base + urllib.parse.quote(str(blob), safe="")
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
                continue
        return {"parse": 1, "jx": 1, "url": "", "header": {}}

    # ------------------------------------------------------------ 直播
    def liveContent(self, url):
        """电视直播（可选能力）"""
        channels = self._req("live/channels", {"page": 1, "page_size": 200})
        if not isinstance(channels, dict):
            return {"class": [], "list": []}
        groups, items = [], []
        seen = set()
        for ch in channels.get("items") or []:
            if not isinstance(ch, dict):
                continue
            g = ch.get("group") or "其他"
            if g not in seen:
                seen.add(g)
                groups.append({"type_id": g, "type_name": g})
            items.append({
                "vod_id": "live_%s" % ch.get("id", ""),
                "vod_name": ch.get("name", ""),
                "vod_pic": ch.get("cover", ""),
                "vod_tag": g,
                "vod_remarks": "直播",
                "vod_play_from": "直播",
                "vod_play_url": "%s$%s" % (ch.get("name", ""), self._pack("live", "", "live", str(ch.get("id", "")))),
            })
        return {"class": groups, "list": items}

    # ------------------------------------------------------------ 工具
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
            "vod_year": str(v.get("vod_year", "") or ""),
            "vod_area": v.get("vod_area", ""),
            "vod_score": str(v.get("vod_score", "")) if v.get("vod_score") else "",
            "vod_content": v.get("vod_content", "") or v.get("vod_blurb", ""),
            "type_name": v.get("vod_type_name", ""),
        }

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass
