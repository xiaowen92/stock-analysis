"""Verify stock codes + fix text formatting → polished verified HTML.

Three-phase pipeline:
  1. Stock verification (yfinance for US, AKShare for CN) + HTML code correction
  2. Text polish via DeepSeek (abbreviations, separators, formatting)
  3. Output _verified.html + _meta.json

Usage:
    python3 scripts/verify.py 文章.html            # Full: verify + polish
    python3 scripts/verify.py --no-polish 文章.html # Stock verify only

Dependencies: yfinance, akshare, openai, beautifulsoup4
"""

import sys
import os
import re
import json
import datetime
from pathlib import Path

import yfinance as yf
from bs4 import BeautifulSoup
from openai import OpenAI

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
CACHE_PATH = Path(__file__).resolve().parent.parent / "references" / "company_db.json"
CACHE_TTL = 30  # days


def cache_load():
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def cache_save(cache):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


def cache_get(key):
    entry = cache_load().get(key.upper())
    if not entry:
        return None
    age = (datetime.datetime.now() - datetime.datetime.fromisoformat(entry["fetched_at"])).days
    return entry["info"] if age <= CACHE_TTL else None


def cache_set(key, info):
    c = cache_load()
    c[key.upper()] = {"fetched_at": datetime.datetime.now().isoformat(), "info": info}
    cache_save(c)


# ---------------------------------------------------------------------------
# Stock verification: US (yfinance) + CN (AKShare)
# ---------------------------------------------------------------------------

def verify_us(ticker):
    """Verify US stock via yfinance. Returns info dict or None."""
    cached = cache_get(ticker)
    if cached:
        return cached

    try:
        tk = yf.Ticker(ticker)
        info = tk.info
        if not info or info.get("symbol") is None:
            cache_set(ticker, {"error": "not_found"})
            return None
        result = {
            "symbol": info.get("symbol", ticker),
            "name": info.get("longName") or info.get("shortName", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market": info.get("exchange", ""),
            "marketCap": info.get("marketCap"),
            "website": info.get("website", ""),
        }
        cache_set(ticker, result)
        return result
    except Exception as e:
        cache_set(ticker, {"error": str(e)[:200]})
        return None


# Lazy-load A-share stock list (code → name mapping)
_CN_STOCKS = None


def _cn_stock_map():
    """Return dict {code: name} for all A-shares. Cached for session, reloaded weekly."""
    global _CN_STOCKS
    cn_cache = cache_get("__CN_STOCK_LIST__")
    if cn_cache and _CN_STOCKS is None:
        _CN_STOCKS = cn_cache
    if _CN_STOCKS is not None:
        return _CN_STOCKS

    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        _CN_STOCKS = dict(zip(df["code"], df["name"]))
        cache_set("__CN_STOCK_LIST__", _CN_STOCKS)
        return _CN_STOCKS
    except Exception:
        return {}


def verify_cn(ticker):
    """Verify China A-share via AKShare. ticker like '600549' (numeric only)."""
    # Normalize: remove .SH/.SZ suffix if present
    ticker = re.sub(r'\.(SH|SZ)$', '', ticker.upper())

    cached = cache_get(ticker)
    if cached:
        return cached

    try:
        stock_map = _cn_stock_map()
        name = stock_map.get(ticker)
        if not name:
            cache_set(ticker, {"error": "not_found"})
            return None

        result = {
            "symbol": ticker,
            "name": name,
            "market": "SH" if ticker.startswith(("6", "68")) else "SZ",
            "sector": "A股",
            "industry": "",
            "marketCap": None,
            "website": "",
        }
        cache_set(ticker, result)
        return result
    except Exception as e:
        cache_set(ticker, {"error": str(e)[:200]})
        return None


# Market suffix patterns → (market_code, display_name)
_MARKET_SUFFIX = {
    ".SH": ("CN", "SSE"),
    ".SZ": ("CN", "SZSE"),
    ".TYO": ("JP", "TSE"),
    ".T": ("JP", "TSE"),
    ".KS": ("KR", "KRX"),
    ".KQ": ("KR", "KOSDAQ"),
    ".DE": ("DE", "FSE"),
    ".F": ("DE", "FSE"),
    ".HK": ("HK", "HKEX"),
    ".TW": ("TW", "TWSE"),
    ".L": ("UK", "LSE"),
}

_MARKET_HINT = re.compile(
    r'(NASDAQ|NYSE|AMEX|OTC|TYO|TSE|KS|KOSPI|KRX|FRA|FSE|XETRA|'
    r'法兰克福|香港|HKEX|TWSE|LSE|伦敦)',
    re.I,
)


def detect_market(ticker, tag_text=""):
    """Detect market from ticker suffix or tag context.

    Returns market code: CN, US, JP, KR, DE, HK, TW, UK.
    """
    t = ticker.upper()

    # Check suffix patterns first (most reliable)
    for suffix, (market, _) in _MARKET_SUFFIX.items():
        if t.endswith(suffix):
            return market

    # Context hints in tag text
    m = _MARKET_HINT.search(tag_text) if tag_text else None
    if m:
        hint = m.group(1).upper()
        if hint in ("NASDAQ", "NYSE", "AMEX", "OTC"):
            return "US"
        if hint in ("TYO", "TSE"):
            return "JP"
        if hint in ("KS", "KOSPI", "KRX"):
            return "KR"
        if hint in ("FRA", "FSE", "XETRA") or hint == "法兰克福":
            return "DE"
        if hint == "HKEX" or hint == "香港":
            return "HK"
        if hint == "TWSE":
            return "TW"
        if hint == "LSE" or hint == "伦敦":
            return "UK"

    # Numeric 6-digit → CN A-share
    if re.match(r'^\d{6}$', ticker):
        return "CN"

    # Plain alphabetic → US (default)
    return "US"


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def _extract_ticker(tag_text):
    """Extract ticker from stock-tag text. Handles multiple formats:

    - "英伟达（NASDAQ：MU）" → MU
    - "厦门钨业（600549.SH）" → 600549.SH
    - "关东电化（4047.TYO）" → 4047.TYO
    - "西昌电力（SH：600505）" → 600505
    - "RCAT" → RCAT
    """
    # Format 1: full-width/half-width parens with colon → extract after colon
    # e.g. "（NASDAQ：MU）" → MU, "（SH：600505）" → 600505
    m = re.search(r'[（(][^）)]*[：:]\s*([A-Za-z0-9.]+)[）)]', tag_text)
    if m:
        return m.group(1)

    # Format 2: parens with dot-suffix ticker → extract with suffix
    # e.g. "（600549.SH）" → 600549.SH, "（4047.TYO）" → 4047.TYO
    m = re.search(r'[（(]([A-Za-z0-9]+(?:\.[A-Za-z0-9]+)?)[）)]', tag_text)
    if m:
        return m.group(1)

    # Format 3: pure ticker, no parens
    # e.g. "RCAT", "ONDS", "AVEX"
    m = re.match(r'^([A-Za-z0-9.]+)$', tag_text)
    if m:
        return m.group(1)

    return None


def parse_stock_tags(html):
    """Return list of (span_soup_element, ticker, tag_full_text)."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for span in soup.find_all("span", class_="stock-tag"):
        text = span.get_text(strip=True)
        ticker = _extract_ticker(text)
        if ticker:
            results.append((span, ticker, text))
    return results


# ---------------------------------------------------------------------------
# Text polish via DeepSeek
# ---------------------------------------------------------------------------
POLISH_PROMPT = """你是一个中文财经文本润色助手。你的任务是修正语音转录文本中的格式问题。

## 你必须做的事

1. **缩写格式化与解释**
   - 将错误大写的缩写修正为正确格式：Idc → IDC，Cpu → CPU，Gpu → GPU，Ai → AI，5g → 5G
   - 对关键行业缩写，在首次出现时补充全称解释：
     IDC → IDC（International Data Corporation，国际数据公司）
     HBM → HBM（High Bandwidth Memory，高带宽内存）
     ETF → ETF（Exchange Traded Fund，交易所交易基金）
     PCB → PCB（Printed Circuit Board，印制电路板）
     SoC → SoC（System on Chip，系统级芯片）
     等，根据上下文判断哪些需要解释

2. **缺少分隔符**
   - 多个英文缩写连写时添加顿号：CPUGPU → CPU、GPU，AIHPC → AI、HPC

3. **数字/日期规范**
   - 保留原文风格，只修正明显的格式错误
   - 中文数字和阿拉伯数字混用的情况统一为阿拉伯数字：二零二六年六月 → 2026年6月

4. **去冗余但保留风格**
   - 删除无意义重复词（"这个这个""就是说就是说"）
   - 保留讲师口语风格和语气

5. **股票代码标签保留**
   - <span class="stock-tag"> 标签及其内容必须保持原样，不要修改

## 严禁做的事

- 严禁添加原文不存在的事实、数据、分析、观点
- 严禁编造任何信息或补充原文没有的内容
- 严禁修改股票标签 <span class="stock-tag"> 的任何内容
- 严禁添加"总结""展望""投资建议"段落或免责声明
- 严禁使用任何 emoji
- 无法确定的内容保持原文
- 只输出润色后的完整 HTML，不要任何额外解释"""


def polish_text(html, api_key):
    """Use DeepSeek to fix text formatting issues in HTML body."""
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")

    response = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=16000,
        temperature=0.0,
        messages=[
            {"role": "system", "content": POLISH_PROMPT},
            {"role": "user", "content": f"请润色以下 HTML 文档，只输出润色后的完整 HTML：\n\n{html}"},
        ],
    )

    result = response.choices[0].message.content.strip()
    if result.startswith("```html"):
        result = result[7:]
    if result.startswith("```"):
        result = result[3:]
    if result.endswith("```"):
        result = result[:-3]
    return result.strip()


# ---------------------------------------------------------------------------
# Phase 2.5: Hard text corrections (safety net for ASR errors)
# ---------------------------------------------------------------------------

HARD_FIXES = [
    ("三宾微课堂", "时寒冰微课堂"),
    ("三滨微课堂", "时寒冰微课堂"),
    ("三斌微课堂", "时寒冰微课堂"),
    ("三宾微课", "时寒冰微课"),
    ("三滨微课", "时寒冰微课"),
    ("三斌微课", "时寒冰微课"),
    ("大家好，欢迎您来到三宾", "大家好，欢迎您来到时寒冰"),
    ("这里是三滨", "这里是时寒冰"),
    ("这里是三宾", "这里是时寒冰"),
    ("德布与TI和加拿大西部精选原油", "WTI和加拿大西部精选原油"),
    ("德布与TI", "WTI"),
]


def apply_hard_fixes(html):
    for wrong, correct in HARD_FIXES:
        if wrong in html:
            html = html.replace(wrong, correct)
    return html


# ---------------------------------------------------------------------------
# Phase 3.5: Tag bare tickers (ZENA, UAVS, etc.) in text
# ---------------------------------------------------------------------------

# Common abbreviations/acronyms that look like tickers but aren't
_TICKER_STOP_WORDS = frozenset({
    "AI", "CPU", "GPU", "SSD", "HBM", "ETF", "IPO", "CEO", "CFO", "COO",
    "GDP", "IOT", "AR", "VR", "MR", "PC", "OS", "UI", "UX", "API", "SDK",
    "USB", "LED", "LCD", "OLED", "RAM", "ROM", "LAN", "WAN", "WIFI", "LTE",
    "SAAS", "PAAS", "IAAS", "QA", "QC", "RND", "BOM", "ROI", "ROE", "PE",
    "PB", "PS", "EPS", "DCF", "IPO", "MNA", "LBO", "KPI", "OKR", "CRM",
    "ERP", "SCM", "HRM", "CMS", "CDN", "DNS", "ISP", "VPN", "SSL", "TLS",
    "HTTP", "HTML", "CSS", "XML", "SQL", "NOSQL", "JSON", "CSV", "YAML",
    "MVC", "OOP", "TDD", "BDD", "CI", "CD", "PR", "MR", "LGTM", "WIP",
    "IMO", "FWIW", "TLDR", "FYI", "ETA", "TBD", "TBA", "N/A", "DIY",
    "OK", "US", "UK", "EU", "UN", "JP", "CN", "KR", "DE", "FR", "IN",
    "COVID", "NASA", "NATO", "OPEC", "FOMC", "SEC", "FDA", "EPA", "IRS",
    "NYSE", "NASDAQ", "AMEX", "OTC", "SSE", "SZSE", "HKEX",
    "USA", "IQ",  # common in product/vendor names, not stock references
})


def _ticker_info_map():
    """Return {ticker: (name, market)} from us_stocks.json for known tickers."""
    us_path = Path(__file__).resolve().parent.parent / "references" / "us_stocks.json"
    if not us_path.exists():
        return {}
    data = json.loads(us_path.read_text())
    result = {}
    for c in data:
        ticker = (c.get("ticker") or "").upper()
        name = c.get("name", "")
        market = c.get("market", "")
        if ticker and name and ticker not in result:
            result[ticker] = (name, market)
    return result


def tag_bare_tickers(html):
    """Scan text for bare ticker symbols (all-caps 2-5 letters), tag verified ones.

    Only tags tickers that appear in us_stocks.json and are not common
    abbreviations/acronyms. Returns (html, newly_tagged).
    """
    ticker_map = _ticker_info_map()
    if not ticker_map:
        return html, []

    soup = BeautifulSoup(html, "html.parser")

    # Collect text nodes not inside existing stock-tag spans
    text_nodes = []
    for node in soup.find_all(string=True):
        parent = node.parent
        if parent and getattr(parent, 'name', '') == 'span' and 'stock-tag' in parent.get('class', []):
            continue
        skip_parents = {'head', 'style', 'script', 'title', 'meta'}
        if parent and any(p.name in skip_parents for p in parent.parents if hasattr(p, 'name')):
            continue
        text_nodes.append(node)

    # Find all unique ticker candidates in text, sorted by length desc
    # Use (?<![A-Za-z])...(?![A-Za-z]) instead of \b because \b treats
    # Chinese characters as word chars, so "是ZENA" has no boundary.
    ticker_re = re.compile(r'(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])')
    candidates = {}
    for node in text_nodes:
        for m in ticker_re.finditer(str(node)):
            t = m.group(1)
            if t not in _TICKER_STOP_WORDS and t in ticker_map and t not in candidates:
                candidates[t] = ticker_map[t]

    if not candidates:
        return html, []

    # Sort by length desc for longest-match-first replacement
    tickers_sorted = sorted(candidates.keys(), key=len, reverse=True)

    newly_tagged = []
    seen_tickers = set()
    regex = re.compile(r'(?<![A-Za-z])(' + '|'.join(re.escape(t) for t in tickers_sorted) + r')(?![A-Za-z])')

    for node in text_nodes:
        text = str(node)
        if not regex.search(text):
            continue
        new_text = regex.sub(
            lambda m: _make_ticker_tag(m.group(1), candidates[m.group(1)]),
            text,
        )
        if new_text != text:
            node.replace_with(BeautifulSoup(new_text, "html.parser"))
            for t in set(regex.findall(text)):
                if t not in seen_tickers:
                    seen_tickers.add(t)
                    name, market = candidates[t]
                    newly_tagged.append((t, t, market, "美股"))

    if newly_tagged:
        print(f"Phase 3.5: 裸代码标注 {len(newly_tagged)} 只")
        for name, ticker, market, mkt_label in newly_tagged:
            print(f"  + [{mkt_label}] {ticker} ({market})")

    return str(soup), newly_tagged


def _make_ticker_tag(ticker, info):
    """Build a stock-tag span from ticker info."""
    name, market = info
    return f'<span class="stock-tag">{name}（{market}：{ticker}）</span>'


# ---------------------------------------------------------------------------
# Phase 3: Tag untagged companies
# ---------------------------------------------------------------------------

def _cn_name_to_code():
    """Return {name: code} map for A-shares (>=4 chars)."""
    stock_map = _cn_stock_map()
    return {name: code for code, name in stock_map.items() if len(name) >= 4}


def _us_name_to_ticker():
    """Return {name: ticker} map for US stocks from cached JSON file.

    Only includes names with Chinese characters (for Chinese articles)
    or long English names >= 10 chars (to avoid false positives from short words).
    """
    us_path = Path(__file__).resolve().parent.parent / "references" / "us_stocks.json"
    if not us_path.exists():
        return {}
    cached = cache_get("__US_NAME_MAP__")
    if cached:
        return cached
    data = json.loads(us_path.read_text())
    name_map = {}
    has_cjk = re.compile(r'[一-鿿]')
    for c in data:
        name = c.get("name", "")
        ticker = c.get("ticker", "")
        market = c.get("market", "")
        if not ticker or _is_etf_or_fund(name):
            continue
        # Accept if contains Chinese chars (>=4 total) OR long English name (>=10 chars)
        if has_cjk.search(name) and len(name) >= 4:
            name_map[name] = (ticker, market)
        elif len(name) >= 10:
            name_map[name] = (ticker, market)
    cache_set("__US_NAME_MAP__", name_map)
    return name_map


def _is_etf_or_fund(name):
    skip = ('ETF', 'Fund', 'ETN', 'Trust', 'Bond', 'Rate', 'Note', 'Income',
            'Acquisition', 'Holdings', 'Capital', 'Growth', 'Value', 'Index')
    return any(w in name for w in skip)


def _all_stock_maps():
    """Return list of dicts: {name: (ticker, market_label, category)}."""
    maps = []
    # A-shares
    cn = _cn_name_to_code()
    if cn:
        cn_info = {name: (code, "SH" if code.startswith(("6","68")) else "SZ", "A股")
                   for name, code in cn.items()}
        maps.append(cn_info)
    # US stocks (English names, filtered)
    us = _us_name_to_ticker()
    if us:
        us_info = {name: (ticker, mkt, "美股")
                   for name, (ticker, mkt) in us.items()}
        maps.append(us_info)
    # Chinese → US/global ticker mapping
    cn_us_path = Path(__file__).resolve().parent.parent / "references" / "us_cn_names.json"
    if cn_us_path.exists():
        data = json.loads(cn_us_path.read_text())
        cn_us_info = {}
        for c in data:
            name = c.get("cn_name", "")
            ticker = c.get("ticker", "")
            market = c.get("market", "")
            if name and ticker and len(name) >= 3:
                cn_us_info[name] = (ticker, market, "美股")
        maps.append(cn_us_info)
    return maps


def tag_missing_companies(html):
    """Scan text for publicly traded company names across all markets.

    Uses AKShare for A-shares + us_stocks.json for US stocks.
    Adds <span class=\"stock-tag\"> for untagged companies.

    Returns (html, newly_tagged) where newly_tagged is a list of
    (name, ticker, market_code, market_label) tuples.
    """
    market_maps = _all_stock_maps()
    if not market_maps:
        return html, []

    soup = BeautifulSoup(html, "html.parser")

    # Collect text nodes not inside existing stock-tag spans
    text_nodes = []
    for node in soup.find_all(string=True):
        parent = node.parent
        if parent and getattr(parent, 'name', '') == 'span' and 'stock-tag' in parent.get('class', []):
            continue
        skip_parents = {'head', 'style', 'script', 'title', 'meta'}
        if parent and any(p.name in skip_parents for p in parent.parents if hasattr(p, 'name')):
            continue
        text_nodes.append(node)

    # Build combined name set sorted by length desc (longest match first)
    all_names = {}
    for mkt_map in market_maps:
        for name, (ticker, market, mkt_label) in mkt_map.items():
            if name not in all_names or mkt_label == "A股":
                all_names[name] = (ticker, market, mkt_label)
    names_sorted = sorted(all_names.keys(), key=len, reverse=True)

    newly_tagged = []
    for node in text_nodes:
        text = str(node)
        for name in names_sorted:
            if name in text:
                ticker, market, mkt_label = all_names[name]
                tag = f'<span class="stock-tag">{name}（{market}：{ticker}）</span>'
                text = text.replace(name, tag)
                newly_tagged.append((name, ticker, market, mkt_label))
                names_sorted.remove(name)
        if text != str(node):
            node.replace_with(BeautifulSoup(text, "html.parser"))

    if newly_tagged:
        print(f"Phase 3: 新标注 {len(newly_tagged)} 只股票")
        for name, ticker, market, mkt_label in newly_tagged:
            print(f"  + [{mkt_label}] {name} ({market}:{ticker})")

    return str(soup), newly_tagged


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    no_polish = "--no-polish" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--no-polish"]

    if len(args) < 1:
        print("用法: python3 scripts/verify.py [--no-polish] <article.html>")
        print("  --no-polish  仅验证股票，跳过文本润色")
        sys.exit(1)

    html_path = args[0]
    if not os.path.exists(html_path):
        print(f"[ERROR] 文件不存在: {html_path}")
        sys.exit(1)

    html = Path(html_path).read_text(encoding="utf-8")
    base = os.path.splitext(html_path)[0]

    # --- Phase 1: Stock verification ---
    stock_spans = parse_stock_tags(html)
    verified = []
    corrections = []

    if stock_spans:
        print(f"Phase 1: 验证 {len(stock_spans)} 只股票...")
        for span, ticker, tag_text in stock_spans:
            market = detect_market(ticker, tag_text)
            print(f"  [{market}] {ticker} ... ", end="")

            if market == "CN":
                num = re.sub(r'\.(SH|SZ)$', '', ticker)
                info = verify_cn(num)
            else:
                info = verify_us(ticker)

            if not info:
                print("NOT FOUND")
                verified.append({"ticker": ticker, "market": market, "verified": False})
                continue

            yf_name = info.get("name", "")
            print(f"{yf_name} [{info.get('market', '?')}]")

            # Check if ticker needs correction
            verified_ticker = info.get("symbol", ticker)
            if verified_ticker.upper() != ticker.upper():
                print(f"    [FIX] {ticker} → {verified_ticker}")
                corrections.append({"original": ticker, "corrected": verified_ticker})
                # Update span text in HTML
                new_tag = tag_text.replace(ticker, verified_ticker)
                html = html.replace(str(span), str(span).replace(tag_text, new_tag))

            verified.append({
                "ticker": verified_ticker,
                "market": market,
                "verified": True,
                "name": yf_name,
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "marketCap": info.get("marketCap") or info.get("totalMarketCap"),
                "website": info.get("website", ""),
            })
    else:
        print("Phase 1: 未找到股票标签，跳过验证")

    # --- Phase 2: Text polish ---
    if not no_polish:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("Phase 2: 未设置 DEEPSEEK_API_KEY，跳过文本润色")
        else:
            print("Phase 2: 文本润色 (DeepSeek)...")
            html = polish_text(html, api_key)
            print("  润色完成")
    else:
        print("Phase 2: --no-polish 跳过文本润色")

    # --- Phase 2.5: Hard fixes ---
    html = apply_hard_fixes(html)

    # --- Phase 3: Tag untagged companies ---
    print("Phase 3: 扫描未标注公司...")
    html, newly_tagged = tag_missing_companies(html)

    # --- Verify Phase 3 additions ---
    if newly_tagged:
        seen_tickers = {c["ticker"] for c in verified}
        print(f"Phase 3: 验证 {len(newly_tagged)} 只新标注股票...")
        for name, ticker, market, mkt_label in newly_tagged:
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
            market_code = detect_market(ticker, "")
            print(f"  [{market_code}] {ticker} ({name}) ... ", end="")

            if market_code == "CN":
                num = re.sub(r'\.(SH|SZ)$', '', ticker)
                info = verify_cn(num)
            elif market_code == "US":
                info = verify_us(ticker)
            else:
                info = verify_us(ticker)  # yfinance for global

            if info:
                print(f"{info.get('name', '?')}")
                verified.append({
                    "ticker": ticker,
                    "market": market_code,
                    "verified": True,
                    "name": info.get("name", name),
                    "sector": info.get("sector", ""),
                    "industry": info.get("industry", ""),
                    "marketCap": info.get("marketCap"),
                    "website": info.get("website", ""),
                })
            else:
                print("NOT FOUND")
                verified.append({
                    "ticker": ticker, "market": market_code, "verified": False,
                    "name": name,
                })

    # --- Phase 3.5: Tag bare tickers ---
    print("Phase 3.5: 扫描裸股票代码...")
    html, bare_tagged = tag_bare_tickers(html)

    # --- Verify Phase 3.5 additions ---
    if bare_tagged:
        seen_tickers = {c["ticker"] for c in verified}
        print(f"Phase 3.5: 验证 {len(bare_tagged)} 只裸代码...")
        for name, ticker, market, mkt_label in bare_tagged:
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
            print(f"  [US] {ticker} ({market}) ... ", end="")

            info = verify_us(ticker)
            if info and info.get("name"):
                print(f"{info['name']}")
                verified.append({
                    "ticker": ticker,
                    "market": "US",
                    "verified": True,
                    "name": info.get("name", name),
                    "sector": info.get("sector", ""),
                    "industry": info.get("industry", ""),
                    "marketCap": info.get("marketCap"),
                    "website": info.get("website", ""),
                })
            else:
                print("NOT FOUND (us_stocks only)")
                verified.append({
                    "ticker": ticker, "market": "US", "verified": True,
                    "name": name,
                })

    # --- Output ---
    # Verified HTML
    html_out = f"{base}_verified.html"
    Path(html_out).write_text(html, encoding="utf-8")
    print(f"\n[Done] {html_out}")

    # Meta JSON
    meta = {
        "source": os.path.basename(html_path),
        "verified_at": datetime.datetime.now().isoformat(),
        "companies": verified,
        "corrections": corrections,
        "polished": not no_polish and bool(os.environ.get("DEEPSEEK_API_KEY")),
    }
    meta_out = f"{base}_meta.json"
    Path(meta_out).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Done] {meta_out}")


if __name__ == "__main__":
    main()
