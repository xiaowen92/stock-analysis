"""Query and trend analysis engine for stock knowledge base.

Generates trend reports for individual stocks, sectors, and themes.
Computes composite scores for 2-3 month trend prediction.

Usage:
    python3 scripts/trend_analysis.py --stock NVDA           # Single stock report
    python3 scripts/trend_analysis.py --sector 半导体          # Sector overview
    python3 scripts/trend_analysis.py --theme 无人机           # Theme analysis
    python3 scripts/trend_analysis.py --rank --top 10         # Top stocks by score
    python3 scripts/trend_analysis.py --summary               # Full knowledge base summary
"""

import sys
import json
import datetime
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
KB_PATH = Path(__file__).resolve().parent.parent / "references" / "stock_knowledge_base.json"

# ---------------------------------------------------------------------------
# Scoring model for 2-3 month trend prediction
# ---------------------------------------------------------------------------
# Weights tuned for medium-term (60-90 day) trend assessment
WEIGHTS = {
    "sentiment_change": 0.30,
    "recency": 0.20,
    "conviction": 0.15,
    "corroboration": 0.15,
    "catalyst_density": 0.10,
    "risk_awareness": 0.10,
}


def parse_date(s):
    """Parse YYYY-MM-DD to date."""
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def days_since(date_str):
    """Days since given date string."""
    d = parse_date(date_str)
    if not d:
        return 999
    return (datetime.date.today() - d).days


def compute_stock_score(stock_data):
    """Compute composite 1-10 trend prediction score for a stock."""
    mentions = stock_data.get("mentions", [])
    if not mentions:
        return None

    # Sort by date
    sorted_m = sorted(mentions, key=lambda m: m.get("transcript_date", ""))
    latest = sorted_m[-1]
    recent = sorted_m[-3:]

    # 1. Sentiment change (-5 to +5), scaled to 0-10
    if len(sorted_m) >= 2 and "sentiment_score" in sorted_m[0] and "sentiment_score" in latest:
        first_score = sorted_m[0].get("sentiment_score", 3)
        latest_score = latest.get("sentiment_score", 3)
        sent_change = latest_score - first_score
        sent_factor = sent_change / 4.0
    else:
        sent_factor = 0.0
    sentiment_raw = 5.0 + sent_factor * 5.0
    sentiment_part = sentiment_raw * WEIGHTS["sentiment_change"]

    # 2. Recency weighting (linear decay over 90 days)
    days = days_since(latest.get("transcript_date", ""))
    recency_factor = max(0, 1.0 - days / 90.0)
    recency_part = recency_factor * 10.0 * WEIGHTS["recency"]

    # 3. Conviction average
    convictions = [m.get("conviction", 0) for m in recent if m.get("conviction")]
    if convictions:
        avg_conv = sum(convictions) / len(convictions)
    else:
        avg_conv = 1.0
    conviction_part = (avg_conv / 5.0) * 10.0 * WEIGHTS["conviction"]

    # 4. Corroboration across themes
    themes = set()
    for m in mentions:
        theme = m.get("transcript_theme", "")
        if theme:
            themes.add(theme)
    corroboration_factor = min(len(themes) / 3.0, 1.0)
    corroboration_part = corroboration_factor * 10.0 * WEIGHTS["corroboration"]

    # 5. Catalyst density
    total_catalysts = sum(len(m.get("catalysts", [])) for m in recent)
    catalyst_factor = min(total_catalysts / 5.0, 1.0)
    catalyst_part = catalyst_factor * 10.0 * WEIGHTS["catalyst_density"]

    # 6. Risk awareness (author acknowledging risks is valuable)
    total_risks = sum(len(m.get("risks", [])) for m in recent)
    risk_factor = min(total_risks / 3.0, 1.0)
    # Risk awareness is positive for analysis quality, but we weigh it lower
    risk_part = risk_factor * 5.0 * WEIGHTS["risk_awareness"]

    # Baseline: latest sentiment score scaled to 1-10
    latest_score = latest.get("sentiment_score", 3)
    baseline = (latest_score - 1) / 4.0 * 9.0 + 1.0
    # We only add a small implicit baseline
    total = sentiment_part + recency_part + conviction_part + \
        corroboration_part + catalyst_part + risk_part

    return round(total, 1)


def sentiment_label(score):
    """Convert numeric score to label."""
    if score is None:
        return "?"
    if score >= 4.5:
        return "强烈看多"
    if score >= 3.5:
        return "看多"
    if score > 2.5:
        return "中性"
    if score > 1.5:
        return "看空"
    return "强烈看空"


def sentiment_bar(score):
    """ASCII bar for sentiment visualization."""
    if score is None:
        return "?" * 10
    n = min(int(score), 10)
    return "█" * n + "░" * (10 - n)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def report_stock(ticker, kb):
    """Generate single-stock trend report."""
    stocks = kb.get("stocks", {})
    data = stocks.get(ticker.upper())
    if not data:
        print(f"[ERROR] 股票 '{ticker}' 不在知识库中")
        return

    score = compute_stock_score(data)
    mentions = sorted(data.get("mentions", []), key=lambda m: m.get("transcript_date", ""))

    market_str = data.get("market", "?")
    sector_str = data.get("sector", "?")
    industry_str = data.get("industry", "?")

    print("─" * 50)
    print(f"  {ticker} 趋势分析报告")
    print(f"  {data.get('name_cn', data.get('name', ''))} ({market_str}) "
          f"| {sector_str} / {industry_str}")
    print(f"  首次提及: {data.get('first_mentioned', '?')} "
          f"| 最近提及: {data.get('last_mentioned', '?')}")
    print(f"  提及次数: {data.get('mention_count', 0)}次 "
          f"(覆盖{data.get('transcript_count', 0)}份转录)")
    print("─" * 50)

    # Sentiment timeline
    print()
    print("情绪轨迹:")
    for m in mentions:
        dt = m.get("transcript_date", "?")
        sent = m.get("sentiment", "?")
        s_score = m.get("sentiment_score", "?")
        conv = m.get("conviction", "?")
        thesis = m.get("thesis_summary", "")
        print(f"  {dt}  {sent}({s_score}/5) | 确信度={conv}/5", end="")
        if thesis:
            print(f"  — {thesis[:60]}")
        else:
            print()

    # Latest thesis
    latest = mentions[-1]
    print()
    print("核心投资论点 (按确信度排序):")
    for i, m in enumerate(mentions):
        for reason in m.get("key_reasons", []):
            print(f"  {i+1}. {reason} — {m.get('transcript_date', '?')}")

    # Catalysts
    all_catalysts = []
    for m in mentions:
        all_catalysts.extend(m.get("catalysts", []))
    if all_catalysts:
        print()
        print("催化剂:")
        for c in all_catalysts:
            print(f"  - {c}")

    # Risks
    all_risks = []
    for m in mentions:
        all_risks.extend(m.get("risks", []))
    if all_risks:
        print()
        print("风险提示:")
        for r in all_risks:
            print(f"  - {r}")

    # Related stocks
    related = defaultdict(int)
    for m in mentions:
        for rs in m.get("related_stocks", []):
            related[rs] += 1
    if related:
        print()
        print("关联股票 (经常共同提及):")
        for rs, count in sorted(related.items(), key=lambda x: -x[1])[:10]:
            rs_data = stocks.get(rs, {})
            rs_name = rs_data.get("name_cn", rs_data.get("name", ""))
            print(f"  {rs} {rs_name} (共同提及{count}次)")

    # Score breakdown
    print()
    print("─" * 50)
    print(f"  综合趋势评分: {score}/10  [{sentiment_bar(score)}]  "
          f"→ {sentiment_label(score)}")


def report_rank(kb, top=10):
    """Rank all stocks by composite score."""
    stocks = kb.get("stocks", {})
    scores = []
    for ticker, data in stocks.items():
        mentions = data.get("mentions", [])
        # Only rank stocks with sentiment analysis
        if not any(m.get("sentiment") for m in mentions):
            continue
        score = compute_stock_score(data)
        if score is not None:
            scores.append((ticker, score, data))

    scores.sort(key=lambda x: -x[1])

    print(f"\n  Top {min(top, len(scores))} 股票走势排名 (2-3月趋势)")
    print("─" * 60)
    print(f"  {'排名':<4} {'代码':<12} {'评分':<6} {'情绪':<10} "
          f"{'确信度':<6} {'提及':<4} {'公司'}")
    print("─" * 60)

    for rank, (ticker, score, data) in enumerate(scores[:top], 1):
        overall = data.get("overall_sentiment", "?")
        avg_conv = data.get("avg_conviction", "?")
        count = data.get("mention_count", 0)
        name = data.get("name_cn", data.get("name", ""))
        print(f"  {rank:<4} {ticker:<12} {score:<6.1f} "
              f"{overall:<10} {avg_conv:<6} {count:<4} {name}")


def report_sector(kb, sector):
    """List all stocks in a given sector."""
    stocks = kb.get("stocks", {})
    sector_lower = sector.lower()

    matched = []
    for ticker, data in stocks.items():
        s = (data.get("sector", "") + " " + data.get("industry", "")).lower()
        if sector_lower in s:
            score = compute_stock_score(data)
            matched.append((ticker, score, data))

    matched.sort(key=lambda x: -(x[1] or 0))

    print(f"\n  行业 [{sector}] — {len(matched)} 只股票")
    print("─" * 50)
    for ticker, score, data in matched:
        name = data.get("name_cn", data.get("name", ""))
        overall = data.get("overall_sentiment", "?")
        print(f"  {ticker:<12} {score or '?':<6} {overall:<10} {name}")


def report_theme(kb, theme):
    """List all stocks in a given investment theme."""
    themes = kb.get("themes", {})
    stocks = kb.get("stocks", {})

    matched_themes = {k: v for k, v in themes.items() if theme in k}
    if not matched_themes:
        print(f"[ERROR] 未找到包含 '{theme}' 的主题")
        return

    for theme_name, theme_data in matched_themes.items():
        print(f"\n  主题: {theme_name}")
        print(f"  覆盖转录: {', '.join(theme_data.get('transcripts', []))}")
        print("─" * 50)

        theme_stocks = []
        for ticker in theme_data.get("stocks", []):
            data = stocks.get(ticker, {})
            score = compute_stock_score(data)
            theme_stocks.append((ticker, score, data))

        theme_stocks.sort(key=lambda x: -(x[1] or 0))
        for ticker, score, data in theme_stocks:
            name = data.get("name_cn", data.get("name", ""))
            overall = data.get("overall_sentiment", "?")
            print(f"  {ticker:<12} {score or '?':<6} {overall:<10} {name}")


def report_summary(kb):
    """Print full knowledge base summary."""
    stocks = kb.get("stocks", {})
    transcripts = kb.get("transcripts", {})
    themes = kb.get("themes", {})

    print(f"\n  知识库摘要")
    print("═" * 60)
    print(f"  股票总数: {len(stocks)}")
    print(f"  转录总数: {len(transcripts)}")
    print(f"  投资主题: {len(themes)}")

    # Sentiment distribution
    sentiment_counts = defaultdict(int)
    analyzed = 0
    for ticker, data in stocks.items():
        overall = data.get("overall_sentiment")
        if overall:
            sentiment_counts[overall] += 1
            analyzed += 1

    print(f"\n  已分析: {analyzed}/{len(stocks)} 只")
    if sentiment_counts:
        print(f"  情绪分布:")
        for s in ("bullish", "bearish", "neutral", "mixed"):
            count = sentiment_counts.get(s, 0)
            bar = "█" * (count // 2) if count else ""
            print(f"    {s:<10} {count:>3}  {bar}")

    # Transcripts
    print(f"\n  转录时间线:")
    for tid, tdata in sorted(transcripts.items(), key=lambda x: x[1].get("date", "")):
        print(f"    {tdata['date']}  {tid[:50]}...  "
              f"({tdata['stock_count']}只)  {tdata['theme'][:40]}")

    # Top themes
    print(f"\n  投资主题 (按覆盖股票数):")
    ranked_themes = sorted(themes.items(), key=lambda x: -len(x[1]["stocks"]))
    for theme, tdata in ranked_themes[:10]:
        print(f"    [{len(tdata['stocks'])}只] {theme[:60]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not KB_PATH.exists():
        print(f"[ERROR] 知识库不存在: {KB_PATH}")
        print("请先运行 build_knowledge_base.py 和 extract_insights.py")
        sys.exit(1)

    kb = json.loads(KB_PATH.read_text())

    args = sys.argv[1:]

    if "--stock" in " ".join(args):
        for i, a in enumerate(args):
            if a == "--stock" and i + 1 < len(args):
                report_stock(args[i + 1], kb)
                return
            elif a.startswith("--stock="):
                report_stock(a.split("=", 1)[1], kb)
                return

    if "--rank" in args:
        top = 10
        for i, a in enumerate(args):
            if a == "--top" and i + 1 < len(args):
                top = int(args[i + 1])
        report_rank(kb, top)
        return

    if "--sector" in " ".join(args):
        for i, a in enumerate(args):
            if a == "--sector" and i + 1 < len(args):
                report_sector(kb, args[i + 1])
                return
            elif a.startswith("--sector="):
                report_sector(kb, a.split("=", 1)[1])
                return

    if "--theme" in " ".join(args):
        for i, a in enumerate(args):
            if a == "--theme" and i + 1 < len(args):
                report_theme(kb, args[i + 1])
                return
            elif a.startswith("--theme="):
                report_theme(kb, a.split("=", 1)[1])
                return

    # Default: summary
    report_summary(kb)


if __name__ == "__main__":
    main()
