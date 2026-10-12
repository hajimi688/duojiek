# coding=utf-8
#!/usr/bin/env python
"""
南枝视汇 TVBox 接口 (Python 版)
--------------------------------
说明：南枝视汇 APK 是加固包（StubApp + libjgcnl*.so），无法静态提取接口。
本文件是标准 TVBox Python 接口框架，已实现完整协议：
  init / homeContent / categoryContent / detailContent / searchContent / playerContent

⚠️ 只需修改下面 [配置区] 的 HOST / 接口路径 / 字段映射，即可接入真实源。
   字段映射不确定时，先只填 HOST，把 DEBUG = True 打开，
   在 TVBox 日志里看原始 JSON 结构，再回来对应修改。

TVBox py 接口要求（务必遵守，否则 TVBox 不认）：
  - 入口函数签名固定：init(cfg) / homeContent(filter) / categoryContent(...) 等
  - 返回值必须是 JSON 字符串（str），不是 dict
  - 视频列表 key 固定：vod_id / vod_name / vod_pic / vod_remarks
  - 播放列表 key 固定：vod_play_from（$$$ 分隔）/ vod_play_url（每集 名称$地址，$$$ 分隔线路，# 分隔集）
"""

import sys
import json
import time

sys.path.append('..')

try:
    import requests
except ImportError:
    requests = None

# ==================== 配置区（改这里） ====================
HOST = "https://请填入抓包得到的域名"

# 各接口路径（抓包后对照修改）
PATH_HOME     = "/api.php/provide/vod/"          # 首页/分类
PATH_DETAIL   = "/api.php/provide/vod/"          # 详情
PATH_SEARCH   = "/api.php/provide/vod/"          # 搜索
PATH_PLAYER   = ""                               # 部分源需要单独解析接口

# 是否需要 siteKey / token 之类的鉴权头
HEADERS = {
    "User-Agent": "okhttp/4.9.0",
    # "siteKey": "填入",
}

# 分类：TVBox 首页/分类导航
CLASSES = [
    {"type_id": "1",  "type_name": "电影"},
    {"type_id": "2",  "type_name": "电视剧"},
    {"type_id": "3",  "type_name": "动漫"},
    {"type_id": "4",  "type_name": "综艺"},
    {"type_id": "5",  "type_name": "短剧"},
]

# 分类对应接口的 category id（若与 type_id 不同，在这里映射）
CATEGORY_MAP = {
    "1": "1",   # 电影
    "2": "2",   # 电视剧
    "3": "3",   # 动漫
    "4": "4",   # 综艺
    "5": "5",   # 短剧
}

# 播放器解析头（有些源要求 Referer / UA）
PLAY_HEADER = ""

# 调试开关：True 时打印原始响应，方便对照字段
DEBUG = False
# =========================================================

TIMEOUT = 12


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def _log(*a):
    if DEBUG:
        print('[南枝视汇]', *a, file=sys.stderr)


def _get(url, params=None):
    """统一请求，自动带 headers"""
    if requests is None:
        raise RuntimeError('缺少 requests 库，请先 pip install requests')
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.encoding = 'utf-8'
    _log('GET', r.url, '->', r.status_code)
    if DEBUG:
        _log('BODY:', r.text[:1500])
    return r.text


def _get_json(url, params=None):
    txt = _get(url, params)
    try:
        return json.loads(txt)
    except Exception:
        # 有些源返回 JSONP，尝试剥壳
        s = txt.find('{')
        e = txt.rfind('}')
        if s >= 0 and e > s:
            return json.loads(txt[s:e + 1])
        return {}


def _fix_pic(pic):
    """补全图片地址"""
    if not pic:
        return ''
    if pic.startswith('//'):
        return 'https:' + pic
    if pic.startswith('/'):
        return HOST.rstrip('/') + pic
    return pic


# ==================== 标准 TVBox 接口 ====================

def init(cfg):
    """初始化，传入 TVBox 的 ext 配置字符串"""
    global HOST, HEADERS
    if cfg and cfg.strip():
        # ext 可以传自定义 host，例如 TVBox 源里写 "ext": "https://xxx.com"
        if cfg.startswith('http'):
            HOST = cfg.strip()
        else:
            # ext 是 JSON 的情况
            try:
                j = json.loads(cfg)
                HOST = j.get('host', HOST)
                if isinstance(j.get('headers'), dict):
                    HEADERS.update(j['headers'])
            except Exception:
                pass
    _log('init host =', HOST)
    return _dumps({'name': '南枝视汇'})


def homeContent(filter=False):
    """首页：返回分类 + 推荐视频"""
    result = {
        'class': CLASSES,
        'filters': {},
        'list': [],
    }
    try:
        data = _get_json(HOST.rstrip('/') + PATH_HOME, {'ac': 'list'})
        result['list'] = _parse_list(data)
    except Exception as e:
        _log('homeContent error:', e)
    return _dumps(result)


def homeVideoContent():
    """首页推荐（部分 TVBox 版本会调）"""
    try:
        data = _get_json(HOST.rstrip('/') + PATH_HOME, {'ac': 'list'})
        return _dumps({'list': _parse_list(data)})
    except Exception as e:
        _log('homeVideoContent error:', e)
        return _dumps({'list': []})


def categoryContent(tid, pg, filter, extend):
    """分类页：tid=分类id pg=页码"""
    result = {
        'page': int(pg),
        'pagecount': 9999,
        'limit': 20,
        'total': 999999,
        'list': [],
    }
    try:
        params = {
            'ac': 'videolist' if 'videolist' in PATH_HOME else 'list',
            't': CATEGORY_MAP.get(str(tid), str(tid)),
            'pg': str(pg),
        }
        if isinstance(extend, dict):
            params.update({k: v for k, v in extend.items() if v})
        data = _get_json(HOST.rstrip('/') + PATH_HOME, params)

        result['list'] = _parse_list(data)
        # 尽量从源里取分页信息
        src_page = data.get('page') or data.get('pagecount')
        src_total = data.get('total')
        src_limit = data.get('limit')
        if src_total:
            result['total'] = int(src_total)
            if src_limit:
                result['limit'] = int(src_limit)
                result['pagecount'] = int(src_total) // int(src_limit) + 1
        if src_page:
            result['pagecount'] = int(src_page)
    except Exception as e:
        _log('categoryContent error:', e)
    return _dumps(result)


def detailContent(ids):
    """详情页：ids=['xxx'] 返回播放列表"""
    result = {'list': []}
    try:
        vid = ids[0] if isinstance(ids, list) else ids
        params = {'ac': 'detail', 'ids': str(vid)}
        if 'videolist' in PATH_DETAIL:
            params = {'ac': 'videolist', 'ids': str(vid)}
        data = _get_json(HOST.rstrip('/') + PATH_DETAIL, params)

        vlist = _raw_vod_list(data)
        if not vlist:
            return _dumps(result)

        v = vlist[0]
        play_from, play_url = _parse_play(v)

        vod = {
            'vod_id': vid,
            'vod_name': v.get('vod_name', ''),
            'vod_pic': _fix_pic(v.get('vod_pic', '')),
            'type_name': v.get('type_name', ''),
            'vod_year': v.get('vod_year', ''),
            'vod_area': v.get('vod_area', ''),
            'vod_remarks': v.get('vod_remarks', ''),
            'vod_actor': v.get('vod_actor', ''),
            'vod_director': v.get('vod_director', ''),
            'vod_content': _clean(v.get('vod_content', '')),
            'vod_play_from': play_from,
            'vod_play_url': play_url,
        }
        result['list'] = [vod]
    except Exception as e:
        _log('detailContent error:', e)
    return _dumps(result)


def searchContent(key, quick=False):
    """搜索"""
    result = {'list': []}
    try:
        params = {'wd': key}
        if 'videolist' in PATH_SEARCH:
            params['ac'] = 'videolist'
        else:
            params['ac'] = 'list'
        data = _get_json(HOST.rstrip('/') + PATH_SEARCH, params)
        result['list'] = _parse_list(data)
    except Exception as e:
        _log('searchContent error:', e)
    return _dumps(result)


def playerContent(flag, id, vipFlags):
    """
    播放解析：flag=线路名 id=播放地址
    返回 {'parse': 0/1, 'url': '真实地址', 'header': ''}
    parse: 0=直接播放  1=需要嗅探解析
    """
    result = {'parse': 0, 'url': id, 'header': PLAY_HEADER}
    try:
        # 有些源需要再请求一次换真实地址
        if PATH_PLAYER:
            data = _get_json(HOST.rstrip('/') + PATH_PLAYER, {'url': id})
            play_url = (data.get('url') or data.get('data', {}).get('url')
                        or data.get('playUrl') or '')
            if play_url:
                result['url'] = play_url
        # m3u8 直链直接播，其余交给 TVBox 嗅探
        u = result['url']
        if '.m3u8' in u or '.mp4' in u or '.flv' in u or '.mkv' in u:
            result['parse'] = 0
        else:
            result['parse'] = 1
    except Exception as e:
        _log('playerContent error:', e)
    return _dumps(result)


# ==================== 解析辅助 ====================

def _raw_vod_list(data):
    """从各种可能的 JSON 结构里取出视频数组"""
    if not isinstance(data, dict):
        return []
    for key in ('list', 'data', 'result', 'videos', 'items'):
        v = data.get(key)
        if isinstance(v, list) and v:
            return v
        if isinstance(v, dict):
            for k2 in ('list', 'data', 'items', 'videos'):
                if isinstance(v.get(k2), list):
                    return v[k2]
    return []


def _pick(d, *keys, default=''):
    """按多个候选字段名取值"""
    for k in keys:
        if k in d and d[k] not in (None, ''):
            return d[k]
    return default


def _parse_list(data):
    """解析视频列表 -> TVBox 格式"""
    out = []
    for v in _raw_vod_list(data):
        if not isinstance(v, dict):
            continue
        out.append({
            'vod_id': _pick(v, 'vod_id', 'id', 'vid', 'ids', 'nid'),
            'vod_name': _pick(v, 'vod_name', 'name', 'title'),
            'vod_pic': _fix_pic(_pick(v, 'vod_pic', 'pic', 'cover', 'img')),
            'vod_remarks': _pick(v, 'vod_remarks', 'remarks', 'note', 'state'),
        })
    return out


def _parse_play(v):
    """
    解析播放地址。
    兼容两种格式：
      1) vod_play_from / vod_play_url 已是 CMS 标准（线路名$$$ 集名$地址#）
      2) 源返回结构化 plays 数组 -> 自己拼
    """
    froms = v.get('vod_play_from')
    urls = v.get('vod_play_url')
    if froms and urls:
        return str(froms), str(urls)

    # 结构化：{"vod_play_list":[{"name":"xx","urls":[{"name":"01","url":"http"}]}]}
    plays = (v.get('vod_play_list') or v.get('plays') or v.get('play_list')
             or v.get('playFrom') or [])
    if isinstance(plays, list) and plays:
        f_list, u_list = [], []
        for p in plays:
            if not isinstance(p, dict):
                continue
            fname = _pick(p, 'name', 'from', 'title') or '线路'
            eps = (p.get('urls') or p.get('url') or p.get('episodes') or [])
            if isinstance(eps, str):
                u_list.append(eps)
                f_list.append(fname)
                continue
            segs = []
            for i, ep in enumerate(eps):
                if isinstance(ep, str):
                    segs.append(f'第{i + 1}集${ep}')
                elif isinstance(ep, dict):
                    en = _pick(ep, 'name', 'title', default=f'第{i + 1}集')
                    eu = _pick(ep, 'url', 'playUrl', 'link')
                    if eu:
                        segs.append(f'{en}${eu}')
            if segs:
                f_list.append(fname)
                u_list.append('#'.join(segs))
        if f_list:
            return '$$$'.join(f_list), '$$$'.join(u_list)

    # 退化：单个 vod_url
    single = _pick(v, 'vod_url', 'url', 'playUrl')
    if single:
        return '默认', f'播放${single}'
    return '', ''


def _clean(html):
    """去标签"""
    if not html:
        return ''
    import re
    return re.sub(r'<[^>]+>', '', str(html)).strip()


# ==================== 本地自测 ====================
if __name__ == '__main__':
    print('--- init ---')
    print(init(''))
    print('--- homeContent ---')
    print(homeContent(False))
    print('--- categoryContent ---')
    print(categoryContent('1', 1, False, {}))
