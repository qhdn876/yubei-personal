"""
FFmpeg 视频去重模块
随机画面微调 + 抽帧 + 亮度/对比度/速度调整, 确保视频独一无二
支持 NVIDIA NVENC / AMD AMF / Intel QSV GPU加速
"""
import os
import re
import random
import subprocess
from pathlib import Path
from typing import Optional
from config import load_config
from logger import get_logger

log = get_logger()

class VideoDeduplicator:
    """视频去重处理器"""
    def __init__(self):
        self.cfg = load_config()
        self.dd_cfg = self.cfg.get("dedup", {})
        self.enabled = self.dd_cfg.get("enabled", True)
        self.output_dir = Path(self.dd_cfg.get("output_dir", "./videos/processed"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.gpu = self.dd_cfg.get("gpu_acceleration", "none")
        self.crop_ratio = self.dd_cfg.get("crop_ratio", 0.03)
        self.frame_skip = self.dd_cfg.get("frame_skip", 0)
        self.brightness_range = self.dd_cfg.get("brightness_range", [-0.05, 0.05])
        self.contrast_range = self.dd_cfg.get("contrast_range", [0.95, 1.05])
        self.speed_range = self.dd_cfg.get("speed_range", [0.97, 1.03])
        self.watermark = self.dd_cfg.get("watermark", {})

    def process_batch(self, video_files: list) -> list:
        """批量处理视频去重, 返回处理后的文件路径列表"""
        if not self.enabled:
            log.info("去重功能已禁用, 跳过处理")
            return [v["filepath"] if isinstance(v, dict) else v for v in video_files]

        if not video_files:
            return []

        log.info(f"开始去重处理: {len(video_files)} 个视频, GPU={self.gpu}")
        results = []
        for idx, item in enumerate(video_files):
            input_path = item["filepath"] if isinstance(item, dict) else item
            try:
                output_path = self.process_single(input_path, idx)
                if output_path:
                    results.append({
                        "filepath": output_path,
                        "title": item.get("title", "") if isinstance(item, dict) else Path(input_path).stem,
                        "source_file": input_path,
                        "original": item if isinstance(item, dict) else {"filepath": input_path},
                    })
            except Exception as e:
                log.error(f"去重处理失败 [{idx}]: {e}")
                # 处理失败时保留原文件
                results.append({"filepath": input_path, "title": Path(input_path).stem, "dedup_failed": True})

        log.info(f"去重处理完成: 成功 {len(results)}/{len(video_files)}")
        return results

    def process_single(self, input_path: str, idx: int = 0) -> Optional[str]:
        """处理单个视频去重"""
        input_file = Path(input_path)
        if not input_file.exists():
            log.error(f"输入文件不存在: {input_path}")
            return None

        output_file = self.output_dir / f"{input_file.stem}_dedup.mp4"
        if output_file.exists():
            log.info(f"输出已存在, 跳过: {output_file.name}")
            return str(output_file)

        # 生成随机参数
        brightness = random.uniform(*self.brightness_range)
        contrast = random.uniform(*self.contrast_range)
        speed = random.uniform(*self.speed_range)
        crop_x = random.randint(0, int(self.crop_ratio * 100))
        crop_y = random.randint(0, int(self.crop_ratio * 100))

        # 构建FFmpeg滤镜链
        filter_parts = []

        # 1. 画面裁剪 (已禁用, 会改变分辨率导致平台不支持; 如需启用请设置 crop_ratio > 0)
        if self.crop_ratio > 0:
            crop_x = random.randint(0, int(self.crop_ratio * 100))
            crop_y = random.randint(0, int(self.crop_ratio * 100))
            crop_w = f"iw*(1-{self.crop_ratio})"
            crop_h = f"ih*(1-{self.crop_ratio})"
            filter_parts.append(f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}")

        # 2. 亮度/对比度调整
        filter_parts.append(f"eq=brightness={brightness:.4f}:contrast={contrast:.4f}")

        # 3. 抽帧去重 (通过setpts实现)
        if self.frame_skip > 0:
            # 每隔N帧删除1帧, 同时调整速度补偿
            select_expr = f"not(mod(n\\,{self.frame_skip + 1}))"
            filter_parts.append(f"select='{select_expr}',setpts=N/FRAME_RATE/TB")
            # 音频也需要相应处理
            audio_filter = f"atempo={speed * (self.frame_skip + 1) / self.frame_skip:.4f}"
        else:
            audio_filter = f"atempo={speed:.4f}"

        # 4. 播放速度调整
        if self.frame_skip == 0:
            filter_parts.append(f"setpts={1/speed:.4f}*PTS")

        # 5. 水印
        if self.watermark.get("enabled") and self.watermark.get("text"):
            wm_text = self.watermark["text"]
            wm_size = self.watermark.get("font_size", 24)
            wm_opacity = self.watermark.get("opacity", 0.3)
            wm_pos = self.watermark.get("position", "bottom-right")
            pos_map = {
                "top-left": "10:10",
                "top-right": "W-w-10:10",
                "bottom-left": "10:H-h-10",
                "bottom-right": "W-w-10:H-h-10",
            }
            pos = pos_map.get(wm_pos, "W-w-10:H-h-10")
            filter_parts.append(
                f"drawtext=text='{wm_text}':fontsize={wm_size}:fontcolor=white@{wm_opacity}:x={pos}"
            )

        video_filter = ",".join(filter_parts)

        # 编码器选择
        if self.gpu == "nvenc":
            vcodec = "h264_nvenc"
            preset = "p4"
        elif self.gpu == "amf":
            vcodec = "h264_amf"
            preset = "balanced"
        elif self.gpu == "qsv":
            vcodec = "h264_qsv"
            preset = "medium"
        else:
            vcodec = "libx264"
            preset = "medium"

        # 构建命令
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_file),
            "-vf", video_filter,
            "-af", audio_filter,
            "-c:v", vcodec,
            "-preset", preset,
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_file),
        ]

        log.debug(f"FFmpeg命令: {' '.join(cmd)}")
        log.info(f"[{idx+1}] 去重处理: {input_file.name} → 亮度={brightness:.3f} 对比度={contrast:.3f} 速度={speed:.3f}")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                log.error(f"FFmpeg处理失败: {result.stderr[-500:]}")
                return None

            if output_file.exists() and output_file.stat().st_size > 1024:
                log.info(f"[{idx+1}] 去重成功: {output_file.name} ({output_file.stat().st_size // 1024}KB)")
                return str(output_file)
            else:
                log.error(f"输出文件异常: {output_file}")
                return None
        except subprocess.TimeoutExpired:
            log.error(f"FFmpeg处理超时: {input_file}")
            return None
        except Exception as e:
            log.error(f"FFmpeg处理异常: {e}")
            return None

    def get_video_info(self, filepath: str) -> dict:
        """获取视频信息 (时长/分辨率/码率)"""
        try:
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
                   "-show_format", "-show_streams", filepath]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            import json
            data = json.loads(result.stdout)
            video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
            return {
                "duration": float(data.get("format", {}).get("duration", 0)),
                "width": video_stream.get("width", 0),
                "height": video_stream.get("height", 0),
                "codec": video_stream.get("codec_name", ""),
                "bitrate": int(data.get("format", {}).get("bit_rate", 0)),
            }
        except Exception as e:
            log.debug(f"获取视频信息失败: {e}")
            return {}
