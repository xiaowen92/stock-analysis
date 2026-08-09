"""Extract stock mentions from calibrated HTML files → stock_knowledge_base.json.

Scans html/ for all transcript HTML files, extracts every stock-tag span with its
surrounding context, and aggregates into a structured knowledge base.

Usage:
    python3 scripts/build_knowledge_base.py              # Build from all HTML files
    python3 scripts/build_knowledge_base.py --dry-run    # Print summary only, no write
"""

import sys
import os
import re
import json
import datetime
from pathlib import Path
from collections import defaultdict

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
KB_PATH = Path(__file__).resolve().parent.parent / "references" / "stock_knowledge_base.json"
HTML_DIR = Path(__file__).resolve().parent.parent / "html"


# ---------------------------------------------------------------------------
# Date mapping: transcript filename → approximate date
# ---------------------------------------------------------------------------
# 旬-based naming convention:
#   上旬篇 = month days 1-10
#   中旬篇 = month days 11-20
#   下旬篇 = month days 21-30
#   末旬篇 = last 10-day period (same as 下旬)

def _parse_date_from_filename(filename):
    """Map transcript filename to approximate date string (YYYY-MM-DD)."""
    name = os.path.splitext(os.path.basename(filename))[0]
    # Remove _verified suffix
    name = re.sub(r'_verified$', '', name)

    # Pattern: 时寒冰-YYYY-陆月-X旬篇-[上下]
    m = re.match(r'时寒冰-(\d{4})-陆月-(上旬|中旬|下旬|末旬)篇[-]?([上下])?', name)
    if m:
        year = int(m.group(1))
        period = m.group(2)
        half = m.group(3)
        # Map 旬 to approximate day
        period_days = {"上旬": 5, "中旬": 15, "下旬": 25, "末旬": 28}
        day = period_days.get(period, 15)
        # If 上下 half is specified: 上=early, 下=late (adjust by ±3 days)
        if half == "上":
            day -= 3
        elif half == "下":
            day += 3
        # Month is June (6)
        month = 6
        return f"{year}-{month:02d}-{day:02d}"

    # Pattern: 6-末-上-钨 or similar
    m = re.match(r'(\d+)-末-([上下])-', name)
    if m:
        year = 2026
        month = int(m.group(1))
        half = m.group(2)
        day = 26 if half == "上" else 29
        return f"{year}-{month:02d}-{day:02d}"

    return None


# ---------------------------------------------------------------------------
# Context extraction
# ---------------------------------------------------------------------------

def extract_transcript_theme(html):
    """Extract h1 title as transcript theme."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def extract_stock_contexts(html, context_radius=2):
    """Extract all stock mentions with surrounding paragraph context.

    Returns list of {ticker, tag_text, contexts, theme}.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Collect all paragraphs in order
    paragraphs = []
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if text:
            paragraphs.append(text)

    # Find all stock-tag spans and their context
    results = []
    for span in soup.find_all("span", class_="stock-tag"):
        tag_text = span.get_text(strip=True)

        # Extract ticker (see verify.py _extract_ticker for equivalent logic)
        ticker = _extract_ticker(tag_text)
        if not ticker:
            continue

        # Find which paragraph contains this span
        parent_p = span.find_parent("p")
        if not parent_p:
            continue
        p_text = parent_p.get_text(strip=True)

        # Find this paragraph's index
        try:
            p_idx = paragraphs.index(p_text)
        except ValueError:
            p_idx = -1

        # Extract context: context_radius paragraphs before and after
        start = max(0, p_idx - context_radius)
        end = min(len(paragraphs), p_idx + context_radius + 1)
        contexts = paragraphs[start:end]

        results.append({
            "ticker": ticker,
            "tag_text": tag_text,
            "p_idx": p_idx,
            "contexts": contexts,
        })

    return results


def _extract_ticker(tag_text):
    """Extract ticker from stock-tag text (mirrors verify.py logic)."""
    # Format: "公司名（市场：代码）" or "公司名（代码）"
    m = re.search(r'[（(][^）)]*[：:]\s*([A-Za-z0-9.]+)[）)]', tag_text)
    if m:
        return m.group(1).upper()
    # Format: "公司名（CODE.SH）"
    m = re.search(r'[（(]([A-Za-z0-9]+(?:\.[A-Za-z0-9]+)?)[）)]', tag_text)
    if m:
        return m.group(1).upper()
    # Format: "CODE"
    m = re.match(r'^([A-Za-z0-9.]+)$', tag_text)
    if m:
        return m.group(1).upper()
    return None


def _extract_name(tag_text):
    """Extract company name from tag text (text before the first paren)."""
    m = re.match(r'^([^（(]+)', tag_text)
    return m.group(1).strip() if m else tag_text


# ---------------------------------------------------------------------------
# Knowledge base building
# ---------------------------------------------------------------------------

def load_existing_kb():
    """Load existing knowledge base or return empty skeleton."""
    if KB_PATH.exists():
        return json.loads(KB_PATH.read_text())
    return {"version": "1.0", "last_updated": "", "stocks": {},
            "transcripts": {}, "themes": {}}


def find_transcript_files():
    """Find unique transcript HTML files. Prefer _verified.html if exists."""
    if not HTML_DIR.exists():
        return []

    # Collect base transcript names
    seen = set()
    files = []

    for f in sorted(HTML_DIR.glob("*.html")):
        name = f.name
        # Skip derived/variant files
        if "_funasr" in name or "_large-v3" in name:
            continue
        # Extract base name
        base = name.replace("_verified.html", ".html").replace(".html", "")
        if base in seen:
            continue
        seen.add(base)

        # Prefer _verified.html if it exists
        verified = HTML_DIR / f"{base}_verified.html"
        if verified.exists():
            files.append(verified)
        else:
            files.append(f)

    files.sort(key=lambda f: f.name)
    return files


def build_knowledge_base(transcript_files, dry_run=False):
    """Build or update knowledge_base.json from transcript HTML files."""
    kb = load_existing_kb()

    for html_path in transcript_files:
        name = html_path.name
        basename = html_path.stem
        print(f"\n{'─'*60}")
        print(f"处理: {name}")

        html = html_path.read_text(encoding="utf-8")
        date = _parse_date_from_filename(basename)
        theme = extract_transcript_theme(html)

        if not date:
            print(f"  [WARNING] 无法解析日期，跳过")
            continue

        # Check if transcript already processed
        transcript_id = basename
        if transcript_id in kb["transcripts"]:
            prev_stocks = kb["transcripts"][transcript_id].get("stocks", [])
            print(f"  [INFO] 已存在，之前有 {len(prev_stocks)} 只股票")
            # Skip if already has stocks
            if prev_stocks:
                continue

        # Extract stock mentions with context
        mentions = extract_stock_contexts(html)
        print(f"  股票标签: {len(mentions)}")

        # Load meta.json for sector/industry data
        meta_path = HTML_DIR / f"{basename}_meta.json"
        meta_companies = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            for c in meta.get("companies", []):
                if c.get("verified"):
                    meta_companies[c["ticker"]] = c

        # Deduplicate by ticker within same transcript (keep first occurrence
        # with most context, deduplicate subsequent occurrences)
        seen_tickers = set()
        transcript_stocks = []

        for m in mentions:
            ticker = m["ticker"]
            name = _extract_name(m["tag_text"])

            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
            transcript_stocks.append(ticker)

            # Build mention entry
            mention_entry = {
                "transcript_id": transcript_id,
                "transcript_date": date,
                "transcript_theme": theme,
                "context_snippets": m["contexts"],
            }

            # Merge meta.json data if available
            meta = meta_companies.get(ticker)
            if meta:
                mention_entry["meta_name"] = meta.get("name", "")
                mention_entry["meta_sector"] = meta.get("sector", "")
                mention_entry["meta_industry"] = meta.get("industry", "")
                mention_entry["meta_marketCap"] = meta.get("marketCap")
            else:
                # Try to detect market from tag text
                tag = m["tag_text"]
                if re.search(r'\.(SH|SZ)', tag):
                    mention_entry["market_hint"] = "CN"
                elif re.search(r'(NASDAQ|NYSE|AMEX|OTC)', tag):
                    mention_entry["market_hint"] = "US"

            # Upsert stock entry in knowledge base
            if ticker not in kb["stocks"]:
                kb["stocks"][ticker] = {
                    "ticker": ticker,
                    "name_cn": name,
                    "first_mentioned": date,
                    "last_mentioned": date,
                    "mention_count": 1,
                    "transcript_count": 1,
                    "mentions": [mention_entry],
                }
                if meta:
                    kb["stocks"][ticker].update({
                        "name": meta.get("name", ""),
                        "sector": meta.get("sector", ""),
                        "industry": meta.get("industry", ""),
                        "marketCap": meta.get("marketCap"),
                        "market": meta.get("market", ""),
                    })
            else:
                stock = kb["stocks"][ticker]
                stock["last_mentioned"] = max(stock["last_mentioned"], date)
                stock["first_mentioned"] = min(stock["first_mentioned"], date)
                stock["mention_count"] += 1
                stock["transcript_count"] = len(set(
                    m2["transcript_id"] for m2 in stock["mentions"]
                ) | {transcript_id})
                stock["mentions"].append(mention_entry)

                # Update name if we have a better one
                if meta and not stock.get("name"):
                    stock["name"] = meta.get("name", "")
                    stock["sector"] = meta.get("sector", "")
                    stock["industry"] = meta.get("industry", "")
                    stock["marketCap"] = meta.get("marketCap")

        # Update transcript index
        kb["transcripts"][transcript_id] = {
            "date": date,
            "theme": theme,
            "stock_count": len(transcript_stocks),
            "stocks": transcript_stocks,
        }

        # Update theme index
        theme_key = theme or basename
        if theme_key not in kb["themes"]:
            kb["themes"][theme_key] = {"stocks": [], "transcripts": []}
        for t in transcript_stocks:
            if t not in kb["themes"][theme_key]["stocks"]:
                kb["themes"][theme_key]["stocks"].append(t)
        if transcript_id not in kb["themes"][theme_key]["transcripts"]:
            kb["themes"][theme_key]["transcripts"].append(transcript_id)

        print(f"  新/更新: {len(transcript_stocks)} 只股票 (累计: {len(kb['stocks'])})")

    # Summary stats
    kb["last_updated"] = datetime.datetime.now().isoformat()
    total_stocks = len(kb["stocks"])
    total_mentions = sum(s["mention_count"] for s in kb["stocks"].values())
    total_transcripts = len(kb["transcripts"])

    print(f"\n{'='*60}")
    print(f"知识库汇总: {total_stocks} 只股票, {total_mentions} 次提及, "
          f"{total_transcripts} 份转录")

    if not dry_run:
        KB_PATH.parent.mkdir(parents=True, exist_ok=True)
        KB_PATH.write_text(json.dumps(kb, ensure_ascii=False, indent=2))
        print(f"[Done] {KB_PATH}")
    else:
        print("[DRY RUN] 未写入文件")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    dry_run = "--dry-run" in sys.argv
    files = find_transcript_files()

    if not files:
        print("未找到 HTML 文件")
        sys.exit(1)

    print(f"找到 {len(files)} 份转录:")
    for f in files:
        date = _parse_date_from_filename(f.stem)
        print(f"  {f.name}  ({date or '日期未知'})")

    build_knowledge_base(files, dry_run=dry_run)


if __name__ == "__main__":
    main()
