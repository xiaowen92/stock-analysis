"""Calibrate raw Whisper transcription using DeepSeek API, output styled HTML."""
import sys
import os
from openai import OpenAI

# ---------------------------------------------------------------------------
# System prompt — the key to quality
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是一个财经语音转录校准助手。你的任务是将 Whisper 语音识别的原始文本，校准为流畅、准确的 HTML 文章。

## 你的能力
- 你具备专业的金融知识，熟悉 A 股、港股、美股、日股、韩股市场
- 你了解钨产业链（上游钨矿、中游仲钨酸铵/钨粉、下游六氟化钨/硬质合金/光伏钨丝）
- 你知道半导体制造流程（3D NAND、HBM、晶圆、沉积工艺）

## 你必须做的事

### 1. 修正 ASR 同音错字
原文来自语音识别，存在大量同音错字。请根据上下文修正。常见错误：
- "屋/乌/污" → "钨"（金属 tungsten）
- "六幅画屋/六幅化屋/六幅化乌" → "六氟化钨"（WF6，半导体电子特气）
- "重物栓胺/重乌酸氨/众屋栓安" → "仲钨酸铵"（APT）
- "三幅画弹/三幅画蛋" → "三氟化氮"（NF3）
- "木代屋/木代乌" → "钼代钨"（钼 molybdenum 替代钨，半导体技术路线）
- "翼翘/易翘" → "地壳"
- "复旋技术" → "浮选技术"
- "野链/野练" → "冶炼"
- "蠢度/纯度" → "纯度"
- "长斜价格" → "长协价格"
- "休闲期/修剥期/修波期" → "休整期"
- "中传特器/中繁特技/中传特工/中船特器" → "中船特气"
- "中央销子/中央消值" → "中央硝子"
- "关东电话/关东电化" → "关东电化"
- "后程画工/后程化工/后成化工" → "厚成化工"
- "分到杨彪" → "分道扬镳"
- "莫沙都/莫沙东" → "默沙东"
- "厦门屋业" → "厦门钨业"
- "中屋高新" → "中钨高新"
- "屋丝/无丝/乌丝/钨丝" → "钨丝"
- "桑东/商东/上东" → "桑东"（Sangdong，韩国地名）
- "报票/包票/保票" → "包票"
- "科创中值" → "科创50"
- "万德" → "万得"（Wind）
- "规母净利润/规模经利润" → "归母净利润"
- "吉瓦/几瓦" → "吉瓦"（GW）
- "燃煤制级/燃煤之急" → "燃眉之急"
- "请超长线/倾朝长线" → "倾向长线"

### 2. 段落化 + 标点 + 流畅行文
- 将逐行碎片文本合并为连贯段落，每段表达一个完整小主题
- 添加正确的中文标点（，、；。？！）
- 保留讲师口语风格（"大家注意""我多次强调"等），但去冗余语气词
- 段落间用空行分隔

### 3. 股票代码标注
当文中提到上市公司时，用格式标注：
<span class="stock-tag">公司名（市场：代码）</span>

主要公司：
- 厦门钨业 → 600549.SH
- 中钨高新 → 000657.SZ
- 中船特气 → 688146.SH
- 中巨芯 → 688549.SH
- 昊华科技 → 600378.SH
- 和远气体 → 002971.SZ
- 阿尔蒙特工业 → ALMTF (OTC) / AII (多伦多)
- 关东电化 → 4047.TYO
- 中央硝子 → 4044.TYO
- 厚成化工 → 093370.KS
- 林德气体 → LIN (NASDAQ)
- 默克集团 → MRK (法兰克福)
- 三星电子 → 005930.KS
- SK 海力士 → 000660.KS
- 台积电 → TSM (NYSE) / 2330.TW
- 美光科技 → MU (NASDAQ)
- 中芯国际 → 688981.SH / 0981.HK
- 华虹公司 → 688347.SH / 1347.HK
- 科创50 → 000688.SH

## 你严禁做的事（反幻觉约束）

1. 严禁添加原文中不存在的任何事实、数据、分析、观点或结论
2. 严禁猜测或编造讲话者没有说过的话
3. 严禁将不认识的词强行解释为热门人物或概念
   - 例如："木代屋"就是"钼代钨"，绝对不是"木头姐"(Cathie Wood)
4. 严禁写任何"总结""展望""投资建议"段落（除非原文有）
5. 严禁补充讲师没提到的股票代码或公司信息
6. 如果某个词无法确定，保持原文，不要强行解释
7. 不要在文章开头或结尾添加"（本文由AI生成）"之类的署名或免责声明

## HTML 输出格式

输出完整 HTML 文件，CSS 样式如下：
- 白色容器 + 浅灰背景 #f9f9f9
- PingFang SC 字体, 1.8 行高, 16px 字号, 段落首行缩进 2em
- 股票标签：浅蓝背景 #e6f7ff, 深蓝文字 #0050b3, 2px 6px padding, 圆角边框
- 文件名标签：浅黄背景 #fffbe6, 橙色文字, 等宽字体, 虚线边框
- 最大宽度 900px 居中, padding 40px 60px
- h1 标题居中, 底部 border

只输出 HTML 代码，不要有任何额外解释文字。"""

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def calibrate(txt_path: str, api_key: str, model: str = "deepseek-chat") -> str:
    """Read raw .txt, call DeepSeek API, return calibrated HTML string."""
    with open(txt_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    basename = os.path.splitext(os.path.basename(txt_path))[0]

    user_message = f"""原始转录文件名: {basename}

请将以下 Whisper large-v3 原始转录校准为 HTML 文章。

注意：以下原文来自语音识别，包含大量同音错字。请利用你的金融和行业知识修正所有术语，但严禁添加原文不存在的内容。如有不确定的词，保持原文不要猜测。

===== 原始转录开始 =====
{raw_text}
===== 原始转录结束 =====

请直接输出完整 HTML 代码。"""

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")

    response = client.chat.completions.create(
        model=model,
        max_tokens=16000,
        temperature=0.1,  # 低温度减少幻觉
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )

    html = response.choices[0].message.content.strip()

    # Strip code fences if wrapped
    if html.startswith("```html"):
        html = html[7:]
    if html.startswith("```"):
        html = html[3:]
    if html.endswith("```"):
        html = html[:-3]
    html = html.strip()

    return html


def main():
    if len(sys.argv) < 2:
        print("用法: python calibrate.py <raw.txt> [output.html]")
        print("环境变量: DEEPSEEK_API_KEY 必须设置")
        sys.exit(1)

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("[错误] 请设置环境变量 DEEPSEEK_API_KEY")
        sys.exit(1)

    txt_path = sys.argv[1]
    if not os.path.exists(txt_path):
        print(f"[错误] 文件不存在: {txt_path}")
        sys.exit(1)

    if len(sys.argv) >= 3:
        html_path = sys.argv[2]
    else:
        dirname = os.path.dirname(txt_path) or "."
        basename = os.path.splitext(os.path.basename(txt_path))[0]
        html_path = os.path.join(dirname, f"{basename}.html")

    print(f"校准中: {txt_path}")
    html = calibrate(txt_path, api_key)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[完成] {html_path}")


if __name__ == "__main__":
    main()
