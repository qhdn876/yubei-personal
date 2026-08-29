"""
头条自动发布模块 (优化版)
- Playwright 浏览器自动化, 登录态持久化
- 发布前重复检查(基于文件哈希)
- 发布后归档到 published/ 目录(对应原项目设计)
- 发布失败移到 failed/ 目录
- 作品声明弹窗自动处理
- 浏览器实例复用
"""
import os
import re
import time
import random
import shutil
from pathlib import Path
from typing import Optional, List
from config import load_config
from logger import get_logger
from cache import get_cache

log = get_logger()

class ToutiaoPublisher:
    """头条自动发布器"""
    def __init__(self):
        self.cfg = load_config()
        self.pub_cfg = self.cfg.get("publisher", {})
        self.enabled = self.pub_cfg.get("enabled", True)
        self.publish_url = self.pub_cfg.get("publish_url", "https://mp.toutiao.com/profile_v4/index")
        self.user_data_dir = Path(self.pub_cfg.get("user_data_dir", "./browser_data/toutiao"))
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.headless = self.pub_cfg.get("headless", False)
        self.publish_interval = self.pub_cfg.get("publish_interval", 120)
        self.timeout = self.pub_cfg.get("timeout", 180)
        self.title_prefix = self.pub_cfg.get("title_prefix", "")
        self.title_suffix = self.pub_cfg.get("title_suffix", "")
        self.auto_title = self.pub_cfg.get("auto_title", {})
        self.cover_mode = self.pub_cfg.get("cover", "auto")
        self.delete_after = self.pub_cfg.get("delete_after_publish", False)
        # 发布后归档(对应原项目设计, 避免重复发布)
        self.archive_after = self.pub_cfg.get("archive_after_publish", True)
        self.archive_dir = Path(self.pub_cfg.get("archive_dir", "./videos/published"))
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        # 发布失败归档
        self.move_failed = self.pub_cfg.get("move_failed", True)
        self.failed_dir = Path(self.pub_cfg.get("failed_dir", "./videos/failed"))
        self.failed_dir.mkdir(parents=True, exist_ok=True)
        # 作品声明弹窗自动处理
        self.auto_handle_declaration = self.pub_cfg.get("auto_handle_declaration", True)
        # 缓存(重复发布检查)
        self.cache = get_cache()
        self._playwright = None
        self._context = None
        self._page = None

    def publish_batch(self, videos: list) -> list:
        """批量发布视频到头条"""
        if not self.enabled:
            log.info("发布功能已禁用")
            return []
        if not videos:
            log.info("没有需要发布的视频")
            return []

        # 发布前重复检查(基于文件内容哈希)
        filtered_videos = []
        skipped = 0
        for video in videos:
            filepath = video["filepath"] if isinstance(video, dict) else video
            if self.cache and self.cache.is_published(filepath):
                log.info(f"跳过已发布视频: {Path(filepath).name}")
                skipped += 1
                continue
            filtered_videos.append(video)
        if skipped > 0:
            log.info(f"重复发布检查: 跳过 {skipped} 个已发布视频, 剩余 {len(filtered_videos)} 个")

        if not filtered_videos:
            log.info("所有视频都已发布过, 无需重复发布")
            return []

        log.info(f"开始批量发布: {len(filtered_videos)} 个视频")
        results = []
        try:
            self._start_browser()
            self._ensure_login()

            for idx, video in enumerate(filtered_videos):
                filepath = video["filepath"] if isinstance(video, dict) else video
                title = video.get("title", "") if isinstance(video, dict) else Path(filepath).stem
                try:
                    success = self._publish_single(filepath, title, idx)
                    results.append({
                        "filepath": filepath,
                        "title": title,
                        "success": success,
                        "published_at": time.strftime("%Y-%m-%d %H:%M:%S") if success else None,
                    })
                    # 发布成功: 记录+归档
                    if success:
                        if self.cache:
                            self.cache.record_published(filepath, title, video.get("source_url", ""), "toutiao")
                        if self.archive_after:
                            self._archive_file(filepath, self.archive_dir)
                        elif self.delete_after:
                            try:
                                os.remove(filepath)
                                log.info(f"已删除源文件: {Path(filepath).name}")
                            except:
                                pass
                    # 发布失败: 移到失败目录
                    elif self.move_failed:
                        self._archive_file(filepath, self.failed_dir)
                except Exception as e:
                    log.error(f"发布异常 [{idx+1}]: {e}")
                    results.append({"filepath": filepath, "title": title, "success": False, "error": str(e)})
                    if self.move_failed:
                        self._archive_file(filepath, self.failed_dir)
                # 发布间隔
                if idx < len(filtered_videos) - 1:
                    wait = self.publish_interval + random.randint(-10, 20)
                    log.info(f"等待 {wait} 秒后发布下一个...")
                    time.sleep(max(wait, 30))
        finally:
            self._close_browser()

        success_count = sum(1 for r in results if r.get("success"))
        log.info(f"批量发布完成: 成功 {success_count}/{len(filtered_videos)}")
        return results

    def _start_browser(self):
        """启动浏览器 (使用持久化用户数据目录保存登录态)"""
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        launch_args = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        }
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            **launch_args,
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._page.set_default_timeout(self.timeout * 1000)
        log.info("浏览器已启动" + (" (无头模式)" if self.headless else ""))

    def _ensure_login(self):
        """确保已登录头条, 未登录则提示扫码"""
        log.info("检查头条登录状态...")
        
        # 如果配置了Cookie, 先设置Cookie
        toutiao_cfg = self.pub_cfg.get("toutiao", {})
        cookie_str = toutiao_cfg.get("cookie", "")
        if cookie_str:
            log.info("检测到配置的Cookie, 正在设置...")
            cookies = []
            for pair in cookie_str.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    cookies.append({
                        "name": name.strip(),
                        "value": value.strip(),
                        "domain": ".toutiao.com",
                        "path": "/"
                    })
            if cookies:
                self._context.add_cookies(cookies)
                log.info(f"已设置 {len(cookies)} 个Cookie")
        
        self._page.goto(self.publish_url, wait_until="domcontentloaded")
        time.sleep(3)
        page_url = self._page.url
        if "login" in page_url or "passport" in page_url:
            if self.headless:
                log.error("无头模式下无法扫码登录, 请先配置Cookie或以 headless=false 运行一次完成登录")
                raise RuntimeError("未登录头条, 请配置 publisher.toutiao.cookie 或设置 headless=false 先扫码登录")
            log.warning("未登录头条, 请在浏览器中扫码登录...")
            for i in range(120):
                time.sleep(1)
                if "login" not in self._page.url and "passport" not in self._page.url:
                    log.info("检测到登录成功!")
                    time.sleep(2)
                    break
            else:
                raise RuntimeError("登录超时")
        else:
            log.info("头条已登录")

    def _publish_single(self, filepath: str, title: str, idx: int) -> bool:
        """发布单个视频"""
        if not Path(filepath).exists():
            log.error(f"视频文件不存在: {filepath}")
            return False

        final_title = self._make_title(title)
        log.info(f"[{idx+1}] 发布: {final_title[:50]}")

        try:
            # 1. 导航到发布页面
            self._page.goto("https://mp.toutiao.com/profile_v4/index", wait_until="domcontentloaded")
            time.sleep(2)

            # 2. 点击"发视频"按钮
            clicked = self._click_upload_button()
            if not clicked:
                log.error("未找到上传视频按钮")
                return False
            time.sleep(2)

            # 3. 上传视频文件
            self._upload_video(filepath)

            # 4. 等待上传完成
            self._wait_for_upload()

            # 5. 填写标题
            self._fill_title(final_title)

            # 6. 处理作品声明弹窗(头条发布时的弹窗)
            if self.auto_handle_declaration:
                self._handle_declaration_popup()

            # 7. 设置封面 (自动从视频截取一帧)
            if self.cover_mode == "auto":
                import subprocess
                cover_path = f"/tmp/cover_{idx}.jpg"
                try:
                    subprocess.run([
                        "ffmpeg", "-y", "-i", filepath,
                        "-ss", "00:00:03", "-vframes", "1",
                        "-q:v", "2", cover_path
                    ], capture_output=True, timeout=30)
                    if Path(cover_path).exists():
                        self._set_cover_auto(cover_path)
                except Exception as e:
                    log.warning(f"截取封面失败: {e}")

            # 8. 点击发布
            self._click_publish()

            log.info(f"[{idx+1}] 发布成功: {final_title[:50]}")
            return True

        except Exception as e:
            log.error(f"[{idx+1}] 发布失败: {e}")
            try:
                screenshot_path = Path(__file__).parent.parent / "logs" / f"publish_error_{idx}.png"
                self._page.screenshot(path=str(screenshot_path))
                log.info(f"失败截图已保存: {screenshot_path}")
            except:
                pass
            return False

    def _click_upload_button(self) -> bool:
        """点击左侧菜单的视频, 进入视频发布页面"""
        try:
            video_menu = self._page.query_selector("text=视频")
            if video_menu:
                video_menu.click()
                time.sleep(3)
                log.info("已点击左侧视频菜单")
                return True
            return False
        except Exception as e:
            log.error(f"点击视频菜单失败: {e}")
            return False

    def _upload_video(self, filepath: str):
        """上传视频文件"""
        file_input = self._page.wait_for_selector("input[type='file']", timeout=15000)
        file_input.set_input_files(filepath)
        log.info(f"已选择文件: {Path(filepath).name}")

    def _wait_for_upload(self):
        """等待视频上传完成"""
        log.info("等待视频上传和转码...")
        time.sleep(5)
        for i in range(60):
            time.sleep(2)
            try:
                progress = self._page.query_selector("[class*='progress'], [class*='uploading']")
                if not progress:
                    title_input = self._page.query_selector("input[placeholder*='标题'], textarea[placeholder*='标题']")
                    if title_input:
                        log.info("上传完成")
                        return
            except:
                pass
        log.warning("上传等待超时, 继续尝试发布")

    def _fill_title(self, title: str):
        """填写视频标题"""
        selectors = [
            "input[placeholder*='标题']",
            "textarea[placeholder*='标题']",
            "input[placeholder*='请输入']",
            "[class*='title'] input",
            "[class*='title'] textarea",
        ]
        for sel in selectors:
            try:
                el = self._page.wait_for_selector(sel, timeout=5000)
                if el and el.is_visible():
                    el.click()
                    el.fill("")
                    el.type(title, delay=50)
                    log.debug(f"标题已填写: {title[:30]}")
                    return
            except:
                continue
        log.warning("未找到标题输入框")

    def _handle_declaration_popup(self):
        """设置作品声明 - 勾选取自站外(搬运视频必选)"""
        try:
            # 勾选"取自站外"
            result = self._page.evaluate('''() => {
                const labels = document.querySelectorAll('label, span, div');
                for (const el of labels) {
                    if (el.innerText && el.innerText.trim() === '取自站外') {
                        el.click();
                        return true;
                    }
                }
                return false;
            }''')
            if result:
                log.info("已勾选作品声明: 取自站外")
            else:
                log.debug("未找到取自站外选项")
            
            time.sleep(1)
            # 关闭可能的弹窗
            self._page.keyboard.press("Escape")
            time.sleep(1)
            
        except Exception as e:
            log.debug(f"设置作品声明异常: {e}")

    def _set_cover_auto(self, cover_path: str = ""):
        """上传封面并处理裁剪弹窗"""
        try:
            if not cover_path or not Path(cover_path).exists():
                log.warning("封面文件不存在, 跳过封面上传")
                return
            
            # 点击上传封面区域
            upload_cover = self._page.query_selector("text=上传封面")
            if upload_cover:
                upload_cover.click()
                time.sleep(2)
            
            # 上传封面文件 (用最后一个file input)
            file_inputs = self._page.query_selector_all("input[type='file']")
            if file_inputs:
                file_inputs[-1].set_input_files(cover_path)
                log.info(f"已上传封面: {Path(cover_path).name}")
                time.sleep(5)
            
            # 处理裁剪弹窗 - 点击确定/完成
            for btn in self._page.query_selector_all("button"):
                try:
                    text = btn.inner_text().strip()
                    if text in ["确定", "完成", "确认", "保存"]:
                        btn.click()
                        log.info("已点击封面裁剪确认")
                        time.sleep(2)
                        break
                except:
                    pass
            
            # 按ESC关闭可能的弹窗
            self._page.keyboard.press("Escape")
            time.sleep(1)
            
        except Exception as e:
            log.warning(f"设置封面异常: {e}")

    def _click_publish(self):
        """点击发布按钮 (先关闭弹窗, 再用JS强制点击)"""
        # 先关闭所有可能的弹窗
        for _ in range(3):
            self._page.keyboard.press("Escape")
            time.sleep(0.5)
        
        # 关闭"我知道了"等提示
        for text in ["我知道了", "知道了", "确定", "取消"]:
            try:
                btn = self._page.query_selector(f"text={text}")
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(1)
            except:
                pass
        
        # 用JS强制点击发布按钮
        result = self._page.evaluate('''() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.innerText.includes('发布') && !btn.disabled) {
                    btn.click();
                    return 'clicked';
                }
            }
            return 'not_found';
        }''')
        
        if result == 'clicked':
            log.info("已点击发布按钮")
            time.sleep(5)
        else:
            raise RuntimeError("未找到可点击的发布按钮")

    def _make_title(self, original_title: str) -> str:
        """生成最终标题"""
        title = original_title.strip()
        if self.auto_title.get("enabled"):
            template = self.auto_title.get("template", "{original}")
            title = template.replace("{original}", title)
        if self.title_prefix:
            title = f"{self.title_prefix}{title}"
        if self.title_suffix:
            title = f"{title}{self.title_suffix}"
        return title[:30]

    def _archive_file(self, filepath: str, target_dir: Path):
        """归档文件到目标目录"""
        try:
            src = Path(filepath)
            if not src.exists():
                return
            target_dir.mkdir(parents=True, exist_ok=True)
            dst = target_dir / src.name
            # 处理重名
            if dst.exists():
                stem = src.stem
                suffix = src.suffix
                counter = 1
                while dst.exists():
                    dst = target_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
            shutil.move(str(src), str(dst))
            log.info(f"文件已归档: {src.name} -> {target_dir.name}/")
        except Exception as e:
            log.error(f"文件归档失败: {e}")

    def _close_browser(self):
        """关闭浏览器"""
        try:
            if self._context:
                self._context.close()
            if self._playwright:
                self._playwright.stop()
            log.info("浏览器已关闭")
        except Exception as e:
            log.debug(f"关闭浏览器异常: {e}")
