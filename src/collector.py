"""
素材采集模块
支持: 创作罐头(czgts.cn) / 头条搜索 / 抖音搜索
"""
import re
import time
import requests
from dataclasses import dataclass, field
from typing import List, Optional
from config import load_config
from logger import get_logger

log = get_logger()

@dataclass
class VideoItem:
    """采集到的视频素材项"""
    url: str                    # 视频页面URL
    title: str = ""             # 标题
    author: str = ""            # 作者
    duration: int = 0           # 时长(秒)
    category: str = ""          # 领域分类
    orientation: str = ""       # landscape / portrait
    cover_url: str = ""         # 封面图
    source: str = ""            # 来源平台
    raw_data: dict = field(default_factory=dict)  # 原始数据

class BaseCollector:
    """采集器基类"""
    def __init__(self):
        self.cfg = load_config()
        self.filter_cfg = self.cfg.get("filter", {})
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def collect(self) -> List[VideoItem]:
        raise NotImplementedError

    def filter_items(self, items: List[VideoItem]) -> List[VideoItem]:
        """应用过滤规则"""
        result = []
        forbidden = self.filter_cfg.get("forbidden_words", [])
        exclude_cats = self.filter_cfg.get("exclude_categories", [])
        min_dur = self.filter_cfg.get("min_duration", 0)
        max_dur = self.filter_cfg.get("max_duration", 99999)
        orientation = self.filter_cfg.get("orientation", "any")

        for item in items:
            # 违禁词过滤
            if forbidden and any(w in item.title for w in forbidden):
                log.debug(f"跳过(违禁词): {item.title[:30]}")
                continue
            # 领域过滤
            if exclude_cats and item.category and any(c in item.category for c in exclude_cats):
                log.debug(f"跳过(领域): {item.category} - {item.title[:30]}")
                continue
            # 时长过滤
            if item.duration and (item.duration < min_dur or item.duration > max_dur):
                log.debug(f"跳过(时长{int(item.duration)}s): {item.title[:30]}")
                continue
            # 横竖屏过滤
            if orientation != "any" and item.orientation and item.orientation != orientation:
                log.debug(f"跳过(方向): {item.orientation} - {item.title[:30]}")
                continue
            result.append(item)

        log.info(f"过滤完成: {len(items)} → {len(result)}")
        return result

class CzgtsCollector(BaseCollector):
    """创作罐头采集器 (czgts.cn) - 低粉爆款/热门素材"""
    def __init__(self):
        super().__init__()
        self.czgts_cfg = self.cfg.get("collector", {}).get("czgts", {})
        self.base_url = self.czgts_cfg.get("base_url", "https://www.czgts.cn")
        cookie = self.czgts_cfg.get("cookie", "")
        if cookie:
            self.session.headers["Cookie"] = cookie
        self.session.headers["Content-Type"] = "application/json"
        self.session.headers["Referer"] = "https://www.czgts.cn/v1/hots/popular"

    def collect(self) -> List[VideoItem]:
        """从创作罐头低粉爆款采集素材"""
        max_count = self.czgts_cfg.get("max_count", 50)
        platform = self.czgts_cfg.get("platform", "今日头条")
        article_genre = self.czgts_cfg.get("article_genre", "视频")
        time_range_hours = self.czgts_cfg.get("time_range_hours", 24)
        sort_by = self.czgts_cfg.get("sort_by", 1)  # 1=综合, 2=阅读量, 3=发布时间

        log.info(f"开始采集创作罐头: platform={platform}, genre={article_genre}, range={time_range_hours}h, max={max_count}")

        items = []
        try:
            from datetime import datetime, timedelta
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            start_time = (datetime.now() - timedelta(hours=time_range_hours)).strftime("%Y-%m-%d %H:%M:%S")

            # 创作罐头低粉爆款API (逆向自真实请求)
            url = f"{self.base_url}/muse/content/api/v1/hots/search"
            payload = {
                "limit": min(max_count, 50),
                "offset": 0,
                "postType": 3,
                "platforms": [platform],
                "categories": [],
                "searchWord": "",
                "sortBy": sort_by,
                "articleGenres": [article_genre],
                "endTime": end_time,
                "startTime": start_time,
                "searchId": "",
            }

            resp = self.session.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                log.error(f"创作罐头API返回异常: code={data.get('code')}, msg={data.get('message')}")
                return []

            raw_list = data.get("list", [])
            log.info(f"API返回 {len(raw_list)} 条, 总数 {data.get('total', 0)}")

            for raw in raw_list[:max_count]:
                item = self._parse_item(raw)
                if item and item.url:
                    items.append(item)

        except Exception as e:
            log.error(f"采集创作罐头失败: {e}")
            log.info("提示: 请检查 config/settings.yaml 中 collector.czgts.cookie 是否正确")

        log.info(f"采集到 {len(items)} 条素材")
        return self.filter_items(items)

    def _parse_item(self, raw: dict) -> Optional[VideoItem]:
        """解析创作罐头返回的单条数据"""
        try:
            url = raw.get("url") or raw.get("video_url") or raw.get("share_url", "")
            title = raw.get("title") or raw.get("desc", "")
            # 从URL判断平台
            source = "toutiao"
            if "douyin" in url or "iesdouyin" in url:
                source = "douyin"
            elif "ixigua" in url or "xigua" in url:
                source = "xigua"
            elif "baijiahao" in url or "baidu" in url:
                source = "baijiahao"

            return VideoItem(
                url=url,
                title=title,
                author=raw.get("authorName") or raw.get("author") or raw.get("nickname", ""),
                duration=raw.get("duration", 0) or 0,
                category=raw.get("category") or raw.get("domain", ""),
                cover_url=raw.get("cover") or raw.get("thumbnail") or raw.get("coverUrl", ""),
                source=source,
                raw_data=raw,
            )
        except Exception as e:
            log.debug(f"解析素材项失败: {e}")
            return None

class ToutiaoSearchCollector(BaseCollector):
    """头条搜索采集器"""
    def collect(self) -> List[VideoItem]:
        cfg = self.cfg.get("collector", {}).get("toutiao_search", {})
        keywords = cfg.get("keywords", [])
        max_per_kw = cfg.get("max_per_keyword", 20)
        items = []

        for kw in keywords:
            log.info(f"头条搜索: {kw}")
            try:
                url = "https://www.toutiao.com/api/search/content/"
                params = {"keyword": kw, "count": max_per_kw, "format": "json"}
                resp = self.session.get(url, params=params, timeout=30)
                data = resp.json()
                for raw in data.get("data", [])[:max_per_kw]:
                    if raw.get("video_duration") or "video" in raw.get("article_type", ""):
                        item = VideoItem(
                            url=f"https://www.toutiao.com{raw.get('article_url', '')}",
                            title=raw.get("title", ""),
                            author=raw.get("source", ""),
                            duration=raw.get("video_duration", 0),
                            source="toutiao",
                            raw_data=raw,
                        )
                        items.append(item)
            except Exception as e:
                log.error(f"头条搜索失败 [{kw}]: {e}")
            time.sleep(2)  # 防限流

        log.info(f"头条搜索采集到 {len(items)} 条")
        return self.filter_items(items)

def get_collector() -> BaseCollector:
    """工厂方法: 根据配置获取采集器"""
    cfg = load_config()
    source = cfg.get("collector", {}).get("source", "czgts")
    collectors = {
        "czgts": CzgtsCollector,
        "toutiao_search": ToutiaoSearchCollector,
    }
    cls = collectors.get(source, CzgtsCollector)
    log.info(f"使用采集器: {cls.__name__}")
    return cls()
