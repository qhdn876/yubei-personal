#!/usr/bin/env python3
"""
宇贝个人版 - 主入口
用法:
  python main.py              # 启动定时调度 (默认)
  python main.py --once       # 立即执行一次
  python main.py --collect    # 仅采集
  python main.py --download   # 仅下载 (需先有采集数据)
  python main.py --publish    # 仅发布本地视频
  python main.py --status     # 查看配置和状态
"""
import sys
import os
import argparse

# 将src目录加入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from logger import get_logger

log = get_logger()

def main():
    parser = argparse.ArgumentParser(description="宇贝个人版 - 视频采集下载去重发布")
    parser.add_argument("--once", action="store_true", help="立即执行一次完整流水线")
    parser.add_argument("--collect", action="store_true", help="仅采集素材")
    parser.add_argument("--download", action="store_true", help="仅下载视频")
    parser.add_argument("--publish", action="store_true", help="仅发布本地视频")
    parser.add_argument("--status", action="store_true", help="查看配置状态")
    parser.add_argument("--monitor", action="store_true", help="启动目录监控模式(视频低于阈值自动采集发布)")
    parser.add_argument("--cache-stats", action="store_true", help="查看缓存统计")
    args = parser.parse_args()

    cfg = load_config()

    if args.status:
        show_status(cfg)
        return

    if args.cache_stats:
        from cache import get_cache
        cache = get_cache()
        stats = cache.get_stats()
        print("\n" + "="*50)
        print("  缓存统计")
        print("="*50)
        print(f"  解析缓存: {stats.get('video_parse_cache', 0)} 条")
        print(f"  发布记录: {stats.get('published_history', 0)} 条")
        print(f"  采集记录: {stats.get('collection_history', 0)} 条")
        print("="*50)
        return

    if args.monitor:
        from monitor import get_monitor
        from scheduler import TaskScheduler
        scheduler = TaskScheduler()
        def on_triggered():
            log.info("[目录监控] 触发完整流水线...")
            scheduler.run_once()
        monitor = get_monitor(on_triggered)
        log.info("启动目录监控模式, Ctrl+C 退出...")
        monitor.start()
        try:
            while True:
                import time
                time.sleep(60)
        except KeyboardInterrupt:
            log.info("收到退出信号, 停止监控...")
            monitor.stop()
        return

    if args.collect:
        from collector import get_collector
        collector = get_collector()
        items = collector.collect()
        log.info(f"采集完成: {len(items)} 条")
        for i, item in enumerate(items[:10]):
            log.info(f"  [{i+1}] {item.title[:50]} ({item.duration}s)")
        return

    if args.download:
        log.error("--download 模式需要先有采集数据, 请使用 --once 完整执行")
        return

    if args.publish:
        from publisher import ToutiaoPublisher
        from pathlib import Path
        pub = ToutiaoPublisher()
        video_dir = Path(cfg.get("dedup", {}).get("output_dir", "./videos/processed"))
        videos = [{"filepath": str(f), "title": f.stem}
                  for f in video_dir.glob("*.mp4")]
        log.info(f"找到 {len(videos)} 个待发布视频")
        pub.publish_batch(videos)
        return

    # 默认: 启动定时调度 或 立即执行一次
    from scheduler import TaskScheduler
    scheduler = TaskScheduler()

    if args.once:
        scheduler.run_once()
    else:
        scheduler.start()

def show_status(cfg):
    """显示配置状态"""
    print("\n" + "="*50)
    print("  宇贝个人版 - 配置状态")
    print("="*50)
    print(f"\n📅 定时调度: {'启用' if cfg.get('scheduler',{}).get('enabled') else '禁用'}")
    print(f"   执行时间: {cfg.get('scheduler',{}).get('daily_times')}")
    print(f"\n🔍 素材来源: {cfg.get('collector',{}).get('source')}")
    print(f"   最大采集: {cfg.get('collector',{}).get('czgts',{}).get('max_count')} 条")
    print(f"\n⬇️  下载并发: {cfg.get('downloader',{}).get('concurrency')}")
    print(f"   输出目录: {cfg.get('downloader',{}).get('output_dir')}")
    print(f"   提取策略: {cfg.get('downloader',{}).get('extract_strategies')}")
    print(f"\n🎬 去重处理: {'启用' if cfg.get('dedup',{}).get('enabled') else '禁用'}")
    print(f"   GPU加速: {cfg.get('dedup',{}).get('gpu_acceleration')}")
    print(f"   输出目录: {cfg.get('dedup',{}).get('output_dir')}")
    print(f"\n📤 自动发布: {'启用' if cfg.get('publisher',{}).get('enabled') else '禁用'}")
    print(f"   无头模式: {cfg.get('publisher',{}).get('headless')}")
    print(f"   发布间隔: {cfg.get('publisher',{}).get('publish_interval')}秒")
    print(f"   发布后归档: {'启用' if cfg.get('publisher',{}).get('archive_after_publish') else '禁用'}")
    print(f"   浏览器数据: {cfg.get('publisher',{}).get('user_data_dir')}")
    print(f"\n💾 本地缓存: {'启用' if cfg.get('cache',{}).get('enabled') else '禁用'}")
    print(f"   缓存数据库: {cfg.get('cache',{}).get('db_path')}")
    print(f"   解析缓存有效期: {cfg.get('cache',{}).get('video_parse_cache',{}).get('ttl_hours')}小时")
    print(f"\n📁 目录监控: {'启用' if cfg.get('monitor',{}).get('enabled') else '禁用'}")
    print(f"   监控目录: {cfg.get('monitor',{}).get('watch_dir')}")
    print(f"   触发阈值: {cfg.get('monitor',{}).get('min_video_threshold')} 个视频")
    print(f"   检查间隔: {cfg.get('monitor',{}).get('check_interval')}秒")
    print(f"\n📢 企微通知: {'已配置' if cfg.get('notifier',{}).get('wecom_webhook') else '未配置'}")
    print("\n" + "="*50)
    print("首次使用请:")
    print("  1. 编辑 config/settings.yaml 配置素材来源和账号")
    print("  2. pip install -r requirements.txt")
    print("  3. playwright install chromium")
    print("  4. python main.py --once  (先以headless=false运行一次扫码登录)")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
