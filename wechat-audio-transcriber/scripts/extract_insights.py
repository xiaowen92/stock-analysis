"""DeepSeek-powered stock sentiment analysis from knowledge base context.

Reads stock_knowledge_base.json, finds stocks that have context_snippets but no
sentiment analysis yet, and calls DeepSeek API to extract:
  - Sentiment (bullish/bearish/neutral/mixed) + 1-5 score
  - Conviction level (1-5)
  - Key bullish reasons / bearish risks / catalysts
  - Investment thesis summary
  - Related stocks

Usage:
    DEEPSEEK_API_KEY=$KEY python3 scripts/extract_insights.py
    DEEPSEEK_API_KEY=$KEY python3 scripts/extract_insights.py --stock NVDA        # Single stock
    DEEPSEEK_API_KEY=$KEY python3 scripts/extract_insights.py --dry-run           # Preview only
"""

import sys
import os
import re
import json
import datetime
from pathlib import Path

from openai import OpenAI

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
KB_PATH = Path(__file__).resolve().parent.parent / "references" / "stock_knowledge_base.json"

# ---------------------------------------------------------------------------
# DeepSeek prompt
# ---------------------------------------------------------------------------
ANALYSIS_PROMPT = """你是一个专业的A股和美股投资分析助手。你的任务是分析财经讲师在语音课程中对某只股票的评论。

## 分析要求

请仔细阅读下面的上下文段落（这些是讲师在课程中提及该股票的相关段落），然后分析讲师的观点。

请返回以下JSON格式的分析结果（只输出JSON，不要额外文字或代码块）：

{
  "sentiment": "bullish|bearish|neutral|mixed",
  "sentiment_score": 1-5,
  "conviction": 1-5,
  "key_reasons": ["看多/看空理由1", "理由2", ...],
  "risks": ["风险1", "风险2", ...],
  "catalysts": ["催化剂1", "催化剂2", ...],
  "thesis_summary": "一句话投资逻辑总结（30字以内）",
  "related_stocks": ["TICKER1", "TICKER2", ...]
}

## 评分标准

- sentiment: bullish(看多), bearish(看空), neutral(中性), mixed(混合/矛盾)
- sentiment_score: 1=强烈看空, 2=偏空, 3=中性, 4=偏多, 5=强烈看多
- conviction: 1=顺带提及无深入分析, 2=简单点评几句话, 3=认真分析有论据, 4=重点推荐反复强调, 5=核心投资建议极有信心
- key_reasons: 列出讲师给出的支持其观点的关键理由（2-5条）
- risks: 列出讲师提到的风险或不利因素（如有，否则空数组）
- catalysts: 列出讲师提到的可能驱动股价的事件（如有，否则空数组）
- thesis_summary: 用一句话概括讲师对该股的投资逻辑
- related_stocks: 同一上下文中提到的其他相关股票代码

## 重要说明

- 只分析讲师的实际观点，不要添加你自己的想法
- 如果上下文信息不足以做出判断，将sentiment设为"neutral"，score=3，conviction=1
- 不要编造讲师没有提到的理由、风险或催化剂
- 如果某只股票只是顺带提到但没有实质性评论，key_reasons可以为空
"""


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def analyze_stock(ticker, stock_data, api_key, model="deepseek-chat"):
    """Analyze a single stock's mentions via DeepSeek.

    For each unanalyzed mention, calls DeepSeek with context paragraphs.
    Updates stock_data in-place.
    """
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")

    name_cn = stock_data.get("name_cn", ticker)
    analyzed = 0

    for i, mention in enumerate(stock_data.get("mentions", [])):
        # Skip if already analyzed
        if "sentiment" in mention and mention.get("conviction"):
            continue

        theme = mention.get("transcript_theme", "")
        contexts = mention.get("context_snippets", [])

        if not contexts:
            continue

        context_text = "\n\n".join(
            f"  [{j+1}] {ctx}" for j, ctx in enumerate(contexts)
        )

        transcript_id = mention.get("transcript_id", "")

        user_msg = f"""## 上下文
股票: {ticker} ({name_cn})
转录主题: {theme}
转录标识: {transcript_id}

### 讲师提及该股票的相关段落:
{context_text}"""

        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=2000,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": ANALYSIS_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )

            raw = response.choices[0].message.content.strip()
            # Strip code fences
            if raw.startswith("```"):
                raw = re.sub(r'^```(?:json)?\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw)

            result = json.loads(raw)

            # Validate and apply
            sentiment = result.get("sentiment", "neutral")
            if sentiment not in ("bullish", "bearish", "neutral", "mixed"):
                sentiment = "neutral"

            score = int(result.get("sentiment_score", 3))
            score = max(1, min(5, score))

            conviction = int(result.get("conviction", 1))
            conviction = max(1, min(5, conviction))

            mention["sentiment"] = sentiment
            mention["sentiment_score"] = score
            mention["conviction"] = conviction
            mention["key_reasons"] = result.get("key_reasons", [])[:5]
            mention["risks"] = result.get("risks", [])[:5]
            mention["catalysts"] = result.get("catalysts", [])[:5]
            mention["thesis_summary"] = result.get("thesis_summary", "")
            mention["related_stocks"] = result.get("related_stocks", [])[:10]

            analyzed += 1
            print(f"  [{ticker}] {sentiment}({score}/5) 确信度={conviction} "
                  f"— {mention.get('thesis_summary', '')[:40]}")

        except json.JSONDecodeError:
            print(f"  [{ticker}] JSON 解析失败，跳过 mention #{i+1}")
            continue
        except Exception as e:
            print(f"  [{ticker}] API 错误: {e}")
            continue

    # Update stock-level aggregates
    if analyzed > 0:
        mentions = stock_data.get("mentions", [])
        if mentions:
            scores = [m.get("sentiment_score", 3) for m in mentions if "sentiment_score" in m]
            convictions = [m.get("conviction", 1) for m in mentions if "conviction" in m]
            sentiments = [m.get("sentiment", "neutral") for m in mentions if "sentiment" in m]

            if scores:
                stock_data["avg_sentiment_score"] = round(sum(scores) / len(scores), 1)
            if convictions:
                stock_data["avg_conviction"] = round(sum(convictions) / len(convictions), 1)

            # Overall sentiment: most common non-neutral, or latest
            non_neutral = [s for s in sentiments if s != "neutral"]
            if non_neutral:
                stock_data["overall_sentiment"] = non_neutral[-1]
            elif sentiments:
                stock_data["overall_sentiment"] = sentiments[-1]

            # Build sentiment timeline
            stock_data["sentiment_timeline"] = [
                {"date": m["transcript_date"],
                 "sentiment": m.get("sentiment", "?"),
                 "score": m.get("sentiment_score", 3),
                 "conviction": m.get("conviction", 1)}
                for m in mentions
                if "sentiment" in m
            ]

            # Latest thesis
            latest_mention = mentions[-1]
            if latest_mention.get("thesis_summary"):
                stock_data["latest_thesis"] = latest_mention["thesis_summary"]

    return analyzed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("[ERROR] 请设置 DEEPSEEK_API_KEY 环境变量")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv
    target_stock = None
    for a in sys.argv[1:]:
        if a.startswith("--stock="):
            target_stock = a.split("=", 1)[1].upper()

    if not KB_PATH.exists():
        print(f"[ERROR] 知识库不存在: {KB_PATH}")
        print("请先运行 build_knowledge_base.py")
        sys.exit(1)

    kb = json.loads(KB_PATH.read_text())
    stocks = kb.get("stocks", {})

    if target_stock:
        if target_stock not in stocks:
            print(f"[ERROR] 股票 '{target_stock}' 不在知识库中")
            sys.exit(1)
        stocks = {target_stock: stocks[target_stock]}

    # Count unanalyzed
    unanalyzed = 0
    for ticker, data in stocks.items():
        for m in data.get("mentions", []):
            if "sentiment" not in m or not m.get("conviction"):
                unanalyzed += 1

    print(f"待分析: {unanalyzed} 次提及 (共 {len(stocks)} 只股票)")
    if dry_run:
        for ticker, data in stocks.items():
            for m in data.get("mentions", []):
                if "sentiment" not in m:
                    ctx_count = len(m.get("context_snippets", []))
                    print(f"  {ticker} — {m['transcript_id']} ({ctx_count} 段上下文)")
        print("\n[DRY RUN] 未调用 API")
        return

    if unanalyzed == 0:
        print("所有提及已分析完毕")
        return

    total = 0
    for ticker, data in stocks.items():
        n = analyze_stock(ticker, data, api_key)
        total += n

    # Save
    kb["last_updated"] = datetime.datetime.now().isoformat()
    KB_PATH.write_text(json.dumps(kb, ensure_ascii=False, indent=2))
    print(f"\n[Done] 分析了 {total} 次新提及 → {KB_PATH}")


if __name__ == "__main__":
    main()
