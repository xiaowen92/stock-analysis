# m4a-txt-converter

微信微课堂音频 (.m4a) → 精美 HTML 文章，基于 Whisper large-v3 + Claude API 校准。

## 流程

```
.m4a → Whisper large-v3 转录 → raw .txt
     → Claude API 校准（修正术语 + 段落化 + 股票代码标注）→ .html
```

## 依赖

```bash
pip install faster-whisper anthropic
```

## 用法

### 单个文件

```bash
# Step 1: 转录
python ../skills/wechat-audio-transcriber/scripts/transcribe.py 课程.m4a

# Step 2: 校准（需要 ANTHROPIC_API_KEY）
ANTHROPIC_API_KEY=your_key python ../skills/wechat-audio-transcriber/scripts/calibrate.py 课程.txt
```

### 批量处理

```bash
export ANTHROPIC_API_KEY=your_key
./batch_transcribe.sh /path/to/recordings/
```

已存在的 .txt / .html 会自动跳过。

## Skill

本项目同时是一个 Claude Code skill，详见 `../skills/wechat-audio-transcriber/SKILL.md`。
