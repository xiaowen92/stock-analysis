#!/bin/bash
# batch_transcribe.sh — 批量转录+校准目录下所有 .m4a 文件
# 用法: ./batch_transcribe.sh [目录路径]
# 如果省略参数，默认为当前目录
#
# 依赖: pip install funasr openai torch torchaudio
# 环境变量 DEEPSEEK_API_KEY 必须设置

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_SCRIPTS="$SCRIPT_DIR/wechat-audio-transcriber/scripts"
DIR="${1:-.}"

echo "=== 批量转录+校准开始 ==="
echo "目录: $DIR"

count=0
for AUDIO in "$DIR"/*.m4a; do
    [ -e "$AUDIO" ] || continue
    count=$((count + 1))
done
echo "文件数: $count"
echo ""

for AUDIO in "$DIR"/*.m4a; do
    [ -e "$AUDIO" ] || continue

    BASENAME="$(basename "$AUDIO" .m4a)"
    TEXT="${DIR}/${BASENAME}.txt"
    HTML="${DIR}/${BASENAME}.html"

    echo "---"
    echo "[处理] $BASENAME"

    # Step 1: Transcribe
    if [ -f "$TEXT" ]; then
        echo "  [1/2] 转录: 已存在，跳过"
    else
        echo "  [1/2] 转录: FunASR Paraformer..."
        python "$SKILL_SCRIPTS/transcribe.py" "$AUDIO"
    fi

    # Step 2: Calibrate
    if [ -f "$HTML" ]; then
        echo "  [2/2] 校准: 已存在，跳过"
    else
        if [ -z "$DEEPSEEK_API_KEY" ]; then
            echo "  [2/2] 校准: 跳过 (未设置 DEEPSEEK_API_KEY)"
        else
            echo "  [2/2] 校准: DeepSeek API..."
            python "$SKILL_SCRIPTS/calibrate.py" "$TEXT" "$HTML"
        fi
    fi

    echo "  [完成]"
done

echo ""
echo "=== 全部完成 ==="
