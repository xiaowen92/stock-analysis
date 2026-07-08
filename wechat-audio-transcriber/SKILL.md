---
name: audio-transcriber
description: Use this skill to transcribe audio recordings (.m4a) into polished, hallucination-free HTML articles with stock code annotations. The skill handles the full pipeline: (1) FunASR Paraformer speech-to-text transcription with VAD + punctuation, (2) DeepSeek API calibration to fix ASR errors, format prose paragraphs, and annotate stock tickers. Triggers when the user asks to transcribe audio, convert recording to text, or generate HTML from recordings.
---

# Audio Transcriber

Transcribe audio recordings (.m4a) into polished HTML articles.

## Pipeline

```
.m4a audio → FunASR Paraformer-large transcription → raw .txt
  → DeepSeek API calibration (fix terms + paragraphs + stock codes) → .html
```

## Performance

| Metric | Value |
|--------|-------|
| Model | FunASR Paraformer-large (Chinese-optimized) |
| VAD | fsmn_vad_zh-cn |
| Punctuation | punc_ct-transformer_zh-cn |
| RTF | ~0.11 (37 min audio → 4 min transcription) |
| Calibration | ~1 min via DeepSeek API |
| Cost | Transcription: free (local); Calibration: ~1-2 CNY/session |
| Hallucination | Zero, with strict anti-hallucination constraints |

## Usage

### Single file

```bash
# Step 1: Transcribe (FunASR Paraformer, local)
python scripts/transcribe.py 课程.m4a

# Step 2: Calibrate (requires DEEPSEEK_API_KEY)
DEEPSEEK_API_KEY=your_key python scripts/calibrate.py 课程.txt
```

### Batch

```bash
./batch_transcribe.sh /path/to/recordings/
```

## Requirements

- `pip install funasr openai torch torchaudio`
- FunASR Paraformer-large model (~1.3GB, downloaded automatically on first run)
- DeepSeek API key for calibration step (set as `DEEPSEEK_API_KEY` env var)

## Files

- `scripts/transcribe.py` — FunASR Paraformer STT with VAD + punctuation
- `scripts/calibrate.py` — DeepSeek API calibration → styled HTML
- `batch_transcribe.sh` — Batch transcribe + calibrate all .m4a files in a directory
- `references/terminology.md` — 钨/tungsten industry ASR error reference
- `evals/evals.json` — Test cases
