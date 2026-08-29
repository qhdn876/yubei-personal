#!/bin/bash
# ============================================================
# 宇贝个人版 - 环境初始化脚本
# 云电脑环境被清理后, 运行此脚本一键恢复
# ============================================================

set -e

echo "=========================================="
echo "  宇贝个人版 - 环境初始化"
echo "=========================================="
echo ""

# 1. 检查Python
echo "[1/5] 检查Python环境..."
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到python3, 请先安装Python 3.8+"
    exit 1
fi
PYTHON_VERSION=$(python3 --version)
echo "   ✅ $PYTHON_VERSION"

# 2. 安装pip依赖
echo ""
echo "[2/5] 安装Python依赖..."
pip3 install --upgrade pip -q
pip3 install -r requirements.txt -q
echo "   ✅ 依赖安装完成"

# 3. 安装Playwright浏览器
echo ""
echo "[3/5] 安装Playwright Chromium浏览器..."
python3 -m playwright install chromium
echo "   ✅ 浏览器安装完成"

# 4. 创建必要目录
echo ""
echo "[4/5] 创建必要目录..."
mkdir -p videos/raw videos/processed videos/published videos/failed
mkdir -p logs data browser_data/toutiao
echo "   ✅ 目录创建完成"

# 5. 检查配置文件
echo ""
echo "[5/5] 检查配置文件..."
if [ ! -f config/settings.yaml ]; then
    if [ -f config/settings.example.yaml ]; then
        cp config/settings.example.yaml config/settings.yaml
        echo "   ⚠️  已从示例创建配置文件, 请编辑 config/settings.yaml 填写Cookie"
    else
        echo "   ⚠️  配置文件不存在, 请手动创建 config/settings.yaml"
    fi
else
    echo "   ✅ 配置文件已存在"
fi

echo ""
echo "=========================================="
echo "  初始化完成!"
echo "=========================================="
echo ""
echo "使用方法:"
echo "  1. 编辑 config/settings.yaml, 填写创作罐头Cookie"
echo "  2. 首次运行(扫码登录头条): cd src && python main.py --run-once"
echo "  3. 定时运行: cd src && python main.py"
echo "  4. 目录监控: cd src && python main.py --monitor"
echo ""
