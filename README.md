# 宇贝个人版 - 视频采集下载去重自动发布

基于原项目逆向重构的纯个人版，砍掉分销/多用户/品牌白标/授权系统，只保留核心链路。

## 核心流程

```
定时触发 → 素材采集(创作罐头/头条搜索) → 智能过滤 → 四重策略下载 → FFmpeg去重 → 头条自动发布 → 企微通知
```

## 项目结构

```
yubei-personal/
├── config/
│   └── settings.yaml          # 所有配置 (定时/采集/过滤/下载/去重/发布/通知)
├── src/
│   ├── main.py                # 主入口
│   ├── config.py              # 配置加载
│   ├── logger.py              # 日志
│   ├── collector.py           # 素材采集 (创作罐头/头条搜索)
│   ├── downloader.py          # 视频下载 (四重策略自动降级)
│   ├── dedup.py               # FFmpeg去重 (裁剪/亮度/对比度/速度/抽帧/水印)
│   ├── publisher.py           # 头条自动发布 (Playwright浏览器自动化)
│   ├── notifier.py            # 企微群通知
│   ├── pipeline.py            # 流程编排
│   └── scheduler.py           # 定时调度 (APScheduler)
├── videos/
│   ├── raw/                   # 下载的原始视频
│   └── processed/             # 去重后的视频
├── browser_data/              # 浏览器登录态 (只需扫码一次)
├── logs/                      # 日志
├── archive/                   # 原项目前端代码归档 (逆向参考)
├── requirements.txt
└── README.md
```

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置
编辑 `config/settings.yaml`：
- **素材来源**：`collector.source` 选 `czgts`(创作罐头) 或 `toutiao_search`(头条搜索)
- **创作罐头Cookie**：如果用 czgts，填 `collector.czgts.cookie`
- **定时时间**：`scheduler.daily_times` (默认每天 8:00/14:00/20:00)
- **过滤规则**：`filter` 下配置违禁词/时长/横竖屏
- **发布**：首次运行保持 `publisher.headless: false` 以便扫码登录

### 3. 首次登录头条 (只需一次)
```bash
cd src
python main.py --once
```
浏览器会自动打开头条创作者中心，扫码登录后登录态自动保存到 `browser_data/`，之后可以改成 `headless: true` 后台运行。

### 4. 启动定时调度
```bash
python main.py              # 启动定时调度 (每天自动执行)
python main.py --once       # 立即执行一次
python main.py --collect    # 仅采集素材
python main.py --publish    # 仅发布本地已处理视频
python main.py --status     # 查看配置状态
```

## 与原项目的对比

| 功能 | 原项目 | 个人版 |
|---|---|---|
| 素材采集 | ✅ 创作罐头 | ✅ 创作罐头 + 头条搜索 |
| 视频下载 | ✅ 四重策略 | ✅ 四重策略 (Playwright DOM + API) |
| FFmpeg去重 | ✅ GPU加速 | ✅ GPU加速 (NVENC/AMF/QSV) |
| 头条发布 | ✅ 多账号批量 | ✅ 单账号自动 |
| 定时调度 | ✅ | ✅ APScheduler |
| 企微通知 | ✅ | ✅ |
| 分销/代理 | ✅ | ❌ 已移除 |
| 多用户管理 | ✅ | ❌ 已移除 |
| 品牌白标 | ✅ | ❌ 已移除 |
| 授权系统 | ✅ | ❌ 已移除 |
| 支付系统 | ✅ | ❌ 已移除 |
| FRP远程控制 | ✅ | ❌ 已移除 (本地运行) |
| Electron桌面端 | ✅ | ❌ 纯Python命令行 (更轻量) |

## 关键配置说明

### 下载提取策略
按优先级自动降级，某策略失败自动切换下一策略：
1. `playwright_dom` - 内置浏览器解析，元数据最完整（时长/分辨率/横竖屏）
2. `api_bugpk` - bugpk解析API，快速轻量
3. `api_jumengfang` - 巨萌坊解析API，备用
4. `api_iiilab` - iiilab解析

可在 `downloader.api_endpoints` 配置自己的解析服务地址。

### FFmpeg去重参数
- `crop_ratio`: 随机裁剪比例 (0.01-0.05)，画面微调
- `brightness_range`: 随机亮度调整
- `contrast_range`: 随机对比度调整
- `speed_range`: 随机播放速度 (0.97-1.03)
- `frame_skip`: 抽帧去重 (每隔N帧删1帧，0=不抽)
- `watermark`: 可选文字水印

### 反爬限流
- 每下载20条休息15秒
- 连续空响应暂停300秒
- 每50条轮换提取策略
- 并发数可配置 (默认3)

## 注意事项

1. **头条登录态**：首次必须用 `headless: false` 扫码，登录态保存在 `browser_data/`，Cookie 过期后需重新扫码
2. **创作罐头Cookie**：使用创作罐头作为素材源时，需要在配置中填写登录后的 Cookie
3. **视频版权**：搬运视频请遵守平台规则和版权法规，建议只做素材参考和二次创作
4. **发布频率**：默认每视频间隔120秒，避免触发平台限流，可根据账号情况调整
5. **磁盘空间**：下载和去重会占用磁盘，建议配置 `publisher.delete_after_publish: true` 发布后自动清理

## 云电脑环境恢复

云电脑环境会定期清理Python包和浏览器，环境被清理后运行：

```bash
# 一键恢复环境 (安装依赖 + 下载浏览器 + 创建目录)
bash setup.sh

# 然后正常运行
cd src
python main.py --once
```

`setup.sh` 会自动完成：
1. 检查Python环境
2. 安装 `requirements.txt` 中的依赖
3. 下载Playwright Chromium浏览器
4. 创建 videos/、logs/、data/、browser_data/ 目录
5. 检查配置文件（从 `config/settings.example.yaml` 复制）

## 配置文件说明

- `config/settings.yaml` - 真实配置（含Cookie，**不提交到GitHub**，已在.gitignore中排除）
- `config/settings.example.yaml` - 配置示例（提交到GitHub，用于环境恢复）

首次克隆仓库后：
```bash
cp config/settings.example.yaml config/settings.yaml
# 然后编辑 config/settings.yaml 填写创作罐头Cookie
```
