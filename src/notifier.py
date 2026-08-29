"""
通知模块 - 企业微信群机器人
"""
import json
import requests
from config import load_config
from logger import get_logger

log = get_logger()

class Notifier:
    def __init__(self):
        self.cfg = load_config()
        self.notifier_cfg = self.cfg.get("notifier", {})
        self.webhook = self.notifier_cfg.get("wecom_webhook", "")
        self.events = self.notifier_cfg.get("events", ["task_complete", "task_error"])

    def send(self, title: str, content: str, msg_type: str = "text"):
        """发送通知"""
        if not self.webhook:
            log.debug("未配置企微Webhook, 跳过通知")
            return
        try:
            if msg_type == "markdown":
                payload = {
                    "msgtype": "markdown",
                    "markdown": {"content": f"### {title}\n{content}"}
                }
            else:
                payload = {
                    "msgtype": "text",
                    "text": {"content": f"[{title}] {content}"}
                }
            resp = requests.post(self.webhook, json=payload, timeout=10)
            if resp.status_code == 200:
                log.info(f"通知已发送: {title}")
            else:
                log.warning(f"通知发送失败: HTTP {resp.status_code}")
        except Exception as e:
            log.debug(f"通知异常: {e}")

    def task_start(self, task_name: str):
        if "task_start" in self.events:
            self.send("任务开始", f"{task_name} 已启动", "markdown")

    def task_complete(self, task_name: str, stats: dict):
        if "task_complete" in self.events:
            lines = [f"**{task_name}** 已完成\n"]
            for k, v in stats.items():
                lines.append(f"- {k}: **{v}**")
            self.send("任务完成", "\n".join(lines), "markdown")

    def task_error(self, task_name: str, error: str):
        if "task_error" in self.events:
            self.send("任务异常", f"{task_name}: {error}", "markdown")

def get_notifier():
    return Notifier()
