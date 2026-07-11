---
name: audio-transcriber
description: Use this skill to record system audio (via BlackHole) or transcribe existing audio into polished, hallucination-free HTML articles with verified stock code annotations. The full pipeline: (1) BlackHole system audio recording with auto output switching, (2) FunASR Paraformer speech-to-text transcription, (3) DeepSeek API calibration to fix ASR errors, format prose paragraphs, and annotate stock tickers, (4) yfinance online verification of stock codes. Triggers when the user asks to record audio, transcribe audio, convert recording to text, or generate HTML from recordings.
---

# Audio Transcriber

Record system audio (via BlackHole) and transcribe into polished HTML articles with verified stock data.

## Directory Structure

```
wechat-audio-transcriber/
├── SKILL.md                  # This file
├── scripts/                  # Pipeline scripts
│   ├── record.py             # BlackHole system audio recording
│   ├── transcribe.py         # FunASR Paraformer STT
│   ├── calibrate.py          # DeepSeek API calibration → HTML
│   └── verify.py             # yfinance stock verification
├── references/               # Reference data (terminology, stock DB)
├── evals/                    # Evaluation test cases
├── txt/                      # Raw transcription output (.txt)
└── html/                     # Calibrated + verified output (.html, _verified.html, _meta.json)
```

**Audio files (.flac)** are stored externally on Google Drive:
`/Users/xiaoyao/Library/CloudStorage/GoogleDrive-wxiao250916@gmail.com/My Drive/录音 股市/`

## Pipeline

```
System Audio → BlackHole → record.py → .flac (Google Drive)
  → FunASR Paraformer-large → txt/ → raw .txt
  → DeepSeek API calibration → html/ → .html
  → yfinance online verification → html/ → _verified.html + _meta.json
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
| Cost | Transcription: free (local); Calibration: ~1-2 CNY/session; Verification: free |
| Hallucination | Zero, with strict anti-hallucination constraints |

## Usage

### Full pipeline (single command)

```bash
# Record + Transcribe + Calibrate + Verify → verified HTML
python3 scripts/record.py -q -d 1800 -o audio.flac
python3 scripts/transcribe.py audio.flac
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY python3 scripts/calibrate.py audio.txt html/audio.html
python3 scripts/verify.py html/audio.html
# → html/audio_verified.html + html/audio_meta.json
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

### Step 3: Verify

```bash
python3 scripts/verify.py html/audio.html
# → html/audio_verified.html   — pass-through HTML (future: auto-correct tickers)
# → html/audio_meta.json       — structured company data for trend analysis
```

## Requirements

| Tool | Install | Purpose |
|------|---------|---------|
| FunASR + DeepSeek SDK | `pip3 install funasr openai torch torchaudio` | Transcription + calibration |
| Recording engine | `pip3 install sounddevice numpy soundfile` | Audio capture |
| Stock verifier | `pip3 install yfinance` | Online stock code verification (free) |
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
| `scripts/verify.py` | yfinance stock verification → _meta.json (free, cached) |
| `txt/` | Raw transcription output (.txt) — gitignored |
| `html/` | Calibrated + verified HTML output (.html, _verified.html, _meta.json) — gitignored |
| `references/terminology.md` | 钨/tungsten industry ASR error reference |
| `references/company_db.json` | Local stock info cache (30-day TTL) |
| `evals/evals.json` | Test cases |
