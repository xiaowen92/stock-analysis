---
name: audio-transcriber
description: Use this skill to record system audio (via BlackHole) or transcribe existing audio into polished, hallucination-free HTML articles with verified stock code annotations. Extended pipeline includes stock knowledge base extraction, DeepSeek sentiment analysis, and 2-3 month trend prediction. Triggers when the user asks to record audio, transcribe audio, convert recording to text, or generate HTML from recordings.
---

# Audio Transcriber

Record system audio (via BlackHole), transcribe into polished HTML articles with verified stock data, and build a structured stock knowledge base for medium-term trend analysis.

## Directory Structure

```
wechat-audio-transcriber/
├── SKILL.md                        # This file
├── scripts/                        # Pipeline scripts
│   ├── record.py                   # BlackHole system audio recording
│   ├── transcribe.py               # FunASR Paraformer STT
│   ├── calibrate.py                # DeepSeek API calibration → HTML
│   ├── verify.py                   # yfinance stock verification (3-phase)
│   ├── build_knowledge_base.py     # Extract stock mentions → JSON
│   ├── extract_insights.py         # DeepSeek sentiment/catalyst analysis
│   └── trend_analysis.py           # Query + trend scoring engine
├── references/                     # Reference data
│   ├── stock_dict.json             # External stock dictionary for calibrate.py
│   ├── stock_knowledge_base.json   # Aggregated stock mentions + sentiment
│   ├── company_db.json             # yfinance/akshare cache (30-day TTL)
│   ├── us_stocks.json              # 10K+ US stock listings
│   ├── us_cn_names.json            # 43 Chinese-name → ticker mappings
│   └── terminology.md              # ASR error correction reference
├── evals/                          # Evaluation test cases
├── txt/                            # Raw transcription output (.txt)
└── html/                           # Calibrated + verified output (.html, _verified.html, _meta.json)
```

**Audio files (.flac)** are stored externally on Google Drive:
`/Users/xiaoyao/Library/CloudStorage/GoogleDrive-wxiao250916@gmail.com/My Drive/录音 股市/`

## Pipeline

```
System Audio → BlackHole → record.py → .flac (Google Drive)
  → FunASR Paraformer-large → txt/ → raw .txt
  → DeepSeek API calibration (with stock_dict.json) → html/ → .html (intermediate)
  → yfinance 3-phase verification → html/ → _verified.html + _meta.json (final)
  → 清理中间 .html → 仅保留 _verified.html
  → build_knowledge_base.py → references/stock_knowledge_base.json
  → extract_insights.py (DeepSeek sentiment) → references/stock_knowledge_base.json (updated)
  → trend_analysis.py → 2-3月趋势报告
```

## 文件清理规则

**仅保留最终版本 `_verified.html`，中间 `.html` 在校验完成后立即删除。**

- `html/xxx.html`（calibrate 输出）→ 仅作为 verify.py 的输入，运行后删除
- `html/xxx_verified.html`（verify 输出）→ 最终交付物，保留
- `html/xxx_meta.json`（验证元数据）→ 保留，供 knowledge base 使用
- `txt/xxx.txt`（原始转录）→ 保留，供归档和 debug
- `.flac`（录音）→ 在 Google Drive 保留

calibrate + verify 命令后自动清理：
```bash
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY python3 scripts/calibrate.py "txt/${BASE}.txt" "html/${BASE}.html" && \
python3 scripts/verify.py "html/${BASE}.html" && \
rm "html/${BASE}.html"
```

## Performance

| Metric | Value |
|--------|-------|
| Model | FunASR Paraformer-large (Chinese-optimized) |
| VAD | fsmn_vad_zh-cn |
| Punctuation | punc_ct-transformer_zh-cn |
| Recording | 48kHz stereo FLAC lossless, via sounddevice (PortAudio) |
| RTF | ~0.11 (37 min audio → 4 min transcription) |
| Calibration | ~1 min via DeepSeek API |
| Verification | ~1-2s per stock via yfinance (free, cached 30 days) |
| Knowledge Base | ~1s per transcript (local HTML parsing) |
| Sentiment Analysis | ~1-2s per stock via DeepSeek API |
| Cost | Transcription: free (local); Calibration: ~1-2 CNY/session; Verification: free; Sentiment: ~0.05 CNY/session |
| Hallucination | Zero, with strict anti-hallucination constraints |

## Usage

### Full pipeline (single command)

```bash
# Record → Transcribe → Calibrate → Verify → Knowledge Base → Sentiment
python3 scripts/record.py -q -d 1800 -o audio.flac
python3 scripts/transcribe.py audio.flac
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY python3 scripts/calibrate.py txt/audio.txt html/audio.html
python3 scripts/verify.py html/audio.html
python3 scripts/build_knowledge_base.py
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY python3 scripts/extract_insights.py
# → references/stock_knowledge_base.json (updated with sentiment)
```

### Step 0: Record

```bash
# Record only — silent, output to Google Drive
AUDIO_DIR="/Users/xiaoyao/Library/CloudStorage/GoogleDrive-wxiao250916@gmail.com/My Drive/录音 股市"
python3 scripts/record.py -q -d 600 -o "$AUDIO_DIR/audio.flac"

# Listen + Record
python3 scripts/record.py -d 600 -o "$AUDIO_DIR/audio.flac"
```

### Step 1: Transcribe

```bash
AUDIO_DIR="/Users/xiaoyao/Library/CloudStorage/GoogleDrive-wxiao250916@gmail.com/My Drive/录音 股市"
python3 scripts/transcribe.py "$AUDIO_DIR/audio.flac"
# → txt/audio.txt
```

### Step 2: Calibrate

```bash
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY python3 scripts/calibrate.py txt/audio.txt html/audio.html
```

Reads `references/stock_dict.json` for company-to-ticker mapping. Add new stocks there before running.

### Step 3: Verify

```bash
python3 scripts/verify.py html/audio.html
python3 scripts/verify.py --no-polish html/audio.html  # Skip DeepSeek polish, verify only
# → html/audio_verified.html   — with Phase 3 auto-tagged companies
# → html/audio_meta.json       — verified company data (US + CN + global)
```

Three verification phases:
1. Parse existing `<span class="stock-tag">` spans → yfinance/akshare verification
2. (Optional) DeepSeek text polish — fix abbreviations, formatting
3. Scan bare text for untagged company names → auto-tag + verify

### Step 4: Build Knowledge Base

```bash
python3 scripts/build_knowledge_base.py
# → references/stock_knowledge_base.json
```

Extracts all stock mentions from `html/*_verified.html` with surrounding paragraph context, merges meta.json data, and deduplicates.

### Step 5: Extract Insights

```bash
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY python3 scripts/extract_insights.py
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY python3 scripts/extract_insights.py --stock NVDA  # Single stock
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY python3 scripts/extract_insights.py --dry-run     # Preview
# → references/stock_knowledge_base.json (updated with sentiment, catalysts, risks)
```

For each stock mention, DeepSeek analyzes:
- Sentiment (bullish/bearish/neutral/mixed) with 1-5 score
- Conviction level (1-5)
- Key reasons, risks, catalysts
- Investment thesis summary
- Related stocks

### Step 6: Trend Analysis

```bash
python3 scripts/trend_analysis.py --stock NVDA        # Single stock report
python3 scripts/trend_analysis.py --rank --top 10     # Top stocks by trend score
python3 scripts/trend_analysis.py --sector 半导体       # Sector overview
python3 scripts/trend_analysis.py --theme 无人机        # Theme analysis
python3 scripts/trend_analysis.py --summary            # Full knowledge base summary
```

### Trend Scoring Model (2-3 Month Prediction)

| Signal | Weight | Description |
|--------|--------|-------------|
| Sentiment change | 30% | Shift in author's sentiment (strongest signal) |
| Recency | 20% | Linear decay over 90 days |
| Conviction | 15% | How strongly the author stated the view |
| Corroboration | 15% | Stock mentioned across multiple themes |
| Catalyst density | 10% | Number of price-moving events identified |
| Risk awareness | 10% | Author-identified risks as confirmation signal |

## Requirements

| Tool | Install | Purpose |
|------|---------|---------|
| FunASR + DeepSeek SDK | `pip3 install funasr openai torch torchaudio` | Transcription + calibration |
| Recording engine | `pip3 install sounddevice numpy soundfile` | Audio capture |
| Stock verifier | `pip3 install yfinance akshare beautifulsoup4` | Stock verification + HTML parsing |
| Audio switcher (macOS) | `brew install switchaudio-osx` | Auto-switch output device |
| BlackHole (macOS) | `brew install --cask blackhole-2ch` | Virtual audio loopback |
| Multi-Output Device | Audio MIDI Setup → + → Speakers + BlackHole 2ch | Listen + Record |

- FunASR Paraformer-large model (~1.3GB, auto-downloaded)
- DeepSeek API key → `DEEPSEEK_API_KEY` env var
- yfinance: free, no API key, results cached locally for 30 days

## Files

| File | Purpose |
|------|---------|
| `scripts/record.py` | System audio recording via BlackHole (auto-switch, FLAC) |
| `scripts/transcribe.py` | FunASR Paraformer STT with VAD + punctuation |
| `scripts/calibrate.py` | DeepSeek API calibration → styled HTML (anti-hallucination, no-emoji) |
| `scripts/verify.py` | 3-phase stock verification + text polish → _verified.html + _meta.json |
| `scripts/build_knowledge_base.py` | Extract stock mentions + context from HTML → knowledge base |
| `scripts/extract_insights.py` | DeepSeek sentiment/catalyst/risk analysis per stock mention |
| `scripts/trend_analysis.py` | Query engine + 2-3 month trend scoring model |
| `references/stock_dict.json` | ~90 curated Chinese-name → ticker mappings for calibration |
| `references/stock_knowledge_base.json` | Aggregated stock mentions with sentiment timeline |
| `references/company_db.json` | yfinance/akshare cache (30-day TTL) |
| `references/us_stocks.json` | 10K+ US stock listings for Phase 3 auto-tagging |
| `references/us_cn_names.json` | 43 Chinese-name → global ticker mappings |
| `references/terminology.md` | ASR error correction reference (钨 industry) |
| `txt/` | Raw transcription output (.txt) |
| `html/` | Calibrated + verified HTML output (.html, _verified.html, _meta.json) |
| `evals/evals.json` | Test cases |
