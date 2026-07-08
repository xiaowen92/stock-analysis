"""Transcribe .m4a audio to text using FunASR Paraformer (Chinese-optimized)."""
import sys
import os
from funasr import AutoModel

# Paraformer-large: best Chinese ASR + VAD + punctuation
MODEL_ID = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"

def main():
    if len(sys.argv) != 2:
        print("用法: python transcribe.py <audio_file.m4a>")
        sys.exit(1)

    audio_path = sys.argv[1]
    if not os.path.exists(audio_path):
        print(f"[错误] 文件不存在: {audio_path}")
        sys.exit(1)

    output_dir = os.path.dirname(audio_path) or "."
    basename = os.path.splitext(os.path.basename(audio_path))[0]
    output_path = os.path.join(output_dir, f"{basename}.txt")

    print(f"加载 FunASR Paraformer-large (中文优化)...")
    model = AutoModel(
        model=MODEL_ID,
        # Use VAD to split long audio, skip silences
        vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
        # Punctuation recovery
        punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
    )

    print(f"转录中: {audio_path}")
    result = model.generate(
        input=audio_path,
        batch_size_s=300,  # process in 300s chunks for long audio
    )

    # FunASR returns list of dicts with 'text' key
    # With VAD+punc, result is one merged string with punctuation
    # Split on Chinese punctuation for line-by-line output
    with open(output_path, "w", encoding="utf-8") as f:
        for item in result:
            text = item.get("text", "")
            # Split on sentence endings, keep the delimiter
            for delimiter in ["。", "？", "！", "；"]:
                text = text.replace(delimiter, delimiter + "\n")
            f.write(text + "\n")

    print(f"[完成] {output_path}")

if __name__ == "__main__":
    main()
