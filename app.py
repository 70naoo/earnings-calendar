import streamlit as st
import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime
import google.generativeai as genai

DATA_FILE = "stocks.json"

st.set_page_config(page_title="株式ダッシュボード", page_icon="📈", layout="wide")

def load_stocks():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return []

def save_stocks(stocks):
    with open(DATA_FILE, "w") as f:
        json.dump(stocks, f)

def get_earnings_date(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        company_name = info.get("longName") or info.get("shortName") or ticker_symbol
        cal = ticker.calendar
        if cal and isinstance(cal, dict) and "Earnings Date" in cal:
            dates = cal["Earnings Date"]
            if dates:
                date_val = dates[0] if isinstance(dates, list) else dates
                if hasattr(date_val, "date"):
                    return company_name, date_val
                return company_name, pd.to_datetime(date_val).date()
        try:
            earnings_dates = ticker.earnings_dates
            if earnings_dates is not None and not earnings_dates.empty:
                future = earnings_dates[earnings_dates.index > pd.Timestamp.now(tz="UTC")]
                if not future.empty:
                    return company_name, future.index[0].date()
                past = earnings_dates[earnings_dates.index <= pd.Timestamp.now(tz="UTC")]
                if not past.empty:
                    return company_name, past.index[0].date()
        except Exception:
            pass
        ts = info.get("earningsTimestamp")
        if ts:
            return company_name, pd.Timestamp(ts, unit="s").date()
        return company_name, None
    except Exception:
        return ticker_symbol, None

@st.cache_data(ttl=1800)
def get_stock_info(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        info = t.info
        name = info.get("longName") or info.get("shortName") or ticker_symbol
        currency = info.get("currency", "JPY")
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
        change_pct = ((price - prev_close) / prev_close * 100) if price and prev_close else None
        week52_high = info.get("fiftyTwoWeekHigh")
        week52_low = info.get("fiftyTwoWeekLow")
        per = info.get("trailingPE")
        pbr = info.get("priceToBook")
        div_yield = info.get("dividendYield")
        analyst = info.get("recommendationKey", "")
        analyst_map = {"buy": "買い", "strong_buy": "強い買い", "hold": "中立", "sell": "売り", "strong_sell": "強い売り"}
        return {
            "name": name, "currency": currency, "price": price,
            "change_pct": change_pct, "week52_high": week52_high,
            "week52_low": week52_low, "per": per, "pbr": pbr,
            "div_yield": div_yield,
            "analyst": analyst_map.get(analyst, analyst),
        }
    except Exception:
        return None

@st.cache_data(ttl=1800)
def get_news(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        news = t.news or []
        items = []
        for n in news[:8]:
            content = n.get("content", {})
            title = content.get("title") or n.get("title", "")
            summary = content.get("summary") or ""
            pub = content.get("pubDate") or n.get("providerPublishTime", "")
            if title:
                items.append({"title": title, "summary": summary, "pub": pub})
        return items
    except Exception:
        return []

def analyze_with_gemini(api_key, ticker, name, info, news_items):
    news_text = "\n".join(
        f"- {n['title']}: {n['summary']}" for n in news_items
    ) if news_items else "ニュースなし"

    prompt = f"""以下の株式について、投資家向けに分析してください。

銘柄: {name}（{ticker}）
現在株価: {info.get('price')} {info.get('currency')}
前日比: {f"{info.get('change_pct'):.2f}%" if info.get('change_pct') else 'N/A'}
52週高値: {info.get('week52_high')} / 52週安値: {info.get('week52_low')}
PER: {info.get('per')} / PBR: {info.get('pbr')}
配当利回り: {f"{info.get('div_yield')*100:.2f}%" if info.get('div_yield') else 'N/A'}
アナリスト評価: {info.get('analyst') or 'N/A'}

最新ニュース:
{news_text}

以下の3点を簡潔に日本語で回答してください：

## 📈 強気材料
（買いを支持する要因を3点）

## 📉 弱気材料
（リスク・懸念点を3点）

## 🔍 今後の注目ポイント
（短期・中期で注目すべきイベントや指標を2〜3点）"""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(prompt)
    return response.text

def parse_rakuten_csv(text):
    import csv, io
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    header_idx = None
    for i, row in enumerate(rows):
        if len(row) >= 2 and row[0].strip() in ("種別", "区分") and "コード" in (row[1] if len(row) > 1 else ""):
            header_idx = i
            break
    if header_idx is None:
        return []
    tickers = []
    for row in rows[header_idx + 1:]:
        if len(row) < 2:
            continue
        category = row[0].strip()
        code = row[1].strip()
        if not code or category in ("投資信託", "外貨MMF", "預り金", ""):
            continue
        if category in ("国内株式", "国内ETF・ETN"):
            tickers.append(f"{code}.T")
        elif category in ("外国株式", "外国ETF", "米国株式", "米国ETF"):
            tickers.append(code.upper())
    return tickers

def days_until(date):
    if date is None:
        return None
    return (date - datetime.today().date()).days

def badge(days):
    if days is None:
        return "⚪ 不明"
    if days < 0:
        return f"✅ {abs(days)}日前に終了"
    if days == 0:
        return "🔴 **本日！**"
    if days <= 3:
        return f"🔴 あと{days}日"
    if days <= 7:
        return f"🟠 あと{days}日"
    if days <= 14:
        return f"🟡 あと{days}日"
    return f"🟢 あと{days}日"

# ── サイドバー ────────────────────────────────────────────
st.sidebar.title("📋 銘柄登録")
st.sidebar.markdown("""
**ティッカーシンボルの入力方法**
- 米国株：`AAPL` `TSLA` `NVDA`
- 日本株：`7203.T` `9984.T`（コード + `.T`）
""")

if "ticker_input" not in st.session_state:
    st.session_state.ticker_input = ""

def add_ticker():
    val = st.session_state.ticker_input.upper().strip()
    stocks = load_stocks()
    if val and val not in stocks:
        stocks.append(val)
        save_stocks(stocks)
        st.session_state.add_message = ("success", f"{val} を追加しました")
    elif val in stocks:
        st.session_state.add_message = ("warning", "すでに登録済みです")
    st.session_state.ticker_input = ""

st.sidebar.text_input("ティッカーシンボル", placeholder="例: AAPL または 7203.T",
                      key="ticker_input", on_change=add_ticker)
if st.sidebar.button("追加", type="primary"):
    add_ticker()

if "add_message" in st.session_state:
    kind, msg = st.session_state.pop("add_message")
    if kind == "success":
        st.sidebar.success(msg)
    else:
        st.sidebar.warning(msg)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📂 CSVから一括追加")
st.sidebar.markdown("楽天証券などのCSVをアップロード")
uploaded = st.sidebar.file_uploader("CSVファイルを選択", type=["csv"], label_visibility="collapsed")

if uploaded:
    try:
        raw = uploaded.read()
        text = None
        for enc in ["cp932", "shift_jis", "utf-8"]:
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            st.sidebar.error("文字コードの判定に失敗しました")
        else:
            tickers_found = parse_rakuten_csv(text)
            if tickers_found:
                st.sidebar.markdown(f"**{len(tickers_found)}銘柄を検出**（投資信託は除外）")
                st.sidebar.dataframe(pd.DataFrame(tickers_found, columns=["ティッカー"]),
                                     hide_index=True, height=150)
                if st.sidebar.button("一括追加", type="primary"):
                    stocks_now = load_stocks()
                    added, skipped = [], []
                    for t in tickers_found:
                        if t not in stocks_now:
                            stocks_now.append(t)
                            added.append(t)
                        else:
                            skipped.append(t)
                    save_stocks(stocks_now)
                    if added:
                        st.sidebar.success(f"{len(added)}銘柄を追加しました")
                    if skipped:
                        st.sidebar.info(f"{len(skipped)}銘柄はすでに登録済みでスキップ")
                    st.rerun()
            else:
                st.sidebar.warning("銘柄が見つかりませんでした")
    except Exception as e:
        st.sidebar.error(f"CSVの読み込みに失敗しました: {e}")

stocks = load_stocks()
if stocks:
    st.sidebar.markdown("---")
    col_title, col_all = st.sidebar.columns([2, 1])
    col_title.markdown("**登録中の銘柄**")
    if col_all.button("全削除", type="secondary"):
        save_stocks([])
        st.rerun()
    for s in stocks:
        col1, col2 = st.sidebar.columns([3, 1])
        col1.write(s)
        if col2.button("削除", key=f"del_{s}"):
            stocks.remove(s)
            save_stocks(stocks)
            st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔑 Gemini APIキー")
api_key_input = st.sidebar.text_input("APIキー", type="password",
                                       placeholder="AIza...",
                                       value=st.session_state.get("api_key", ""))
if api_key_input:
    st.session_state["api_key"] = api_key_input

# ── メイン画面：タブ ──────────────────────────────────────
if not stocks:
    st.info("👈 左のサイドバーから銘柄を登録してください")
    st.stop()

tab1, tab2 = st.tabs(["📅 決算カレンダー", "📊 ポートフォリオ分析"])

# ── タブ1：決算カレンダー ─────────────────────────────────
with tab1:
    st.title("📅 決算カレンダー")
    st.caption(f"最終更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

    col1, col2 = st.columns([2, 2])
    with col1:
        filter_days = st.selectbox("表示期間", ["全て", "7日以内", "14日以内", "30日以内"])
    with col2:
        if st.button("🔄 データ更新"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("---")

    @st.cache_data(ttl=3600)
    def fetch_all(tickers):
        results = []
        for t in tickers:
            name, date = get_earnings_date(t)
            results.append({"ticker": t, "name": name, "date": date, "days": days_until(date)})
        return results

    with st.spinner("決算日を取得中..."):
        data = fetch_all(tuple(stocks))

    if filter_days == "7日以内":
        data = [d for d in data if d["days"] is not None and 0 <= d["days"] <= 7]
    elif filter_days == "14日以内":
        data = [d for d in data if d["days"] is not None and 0 <= d["days"] <= 14]
    elif filter_days == "30日以内":
        data = [d for d in data if d["days"] is not None and 0 <= d["days"] <= 30]

    data_sorted = sorted(data, key=lambda x: (x["days"] is None, x["days"] if x["days"] is not None else 9999))

    alert_count = sum(1 for d in data if d["days"] is not None and 0 <= d["days"] <= 7)
    if alert_count > 0:
        st.warning(f"⚠️ 7日以内に決算がある銘柄が **{alert_count}件** あります")

    if not data_sorted:
        st.info("該当する銘柄がありません")
    else:
        for d in data_sorted:
            with st.container():
                c1, c2, c3, c4 = st.columns([2, 3, 2, 2])
                c1.markdown(f"**{d['ticker']}**")
                c2.write(d["name"] if d["name"] != d["ticker"] else "—")
                c3.write(d["date"].strftime("%Y-%m-%d") if d["date"] else "取得できず")
                c4.markdown(badge(d["days"]))
            st.divider()

# ── タブ2：ポートフォリオ分析 ─────────────────────────────
with tab2:
    st.title("📊 ポートフォリオ分析")
    st.caption(f"最終更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

    if st.button("🔄 データ更新", key="refresh_portfolio"):
        st.cache_data.clear()
        st.rerun()

    with st.spinner("株価データを取得中..."):
        portfolio_data = {s: get_stock_info(s) for s in stocks}

    # サマリーカード
    valid = {k: v for k, v in portfolio_data.items() if v}
    if valid:
        cols = st.columns(min(len(valid), 4))
        for i, (ticker, info) in enumerate(list(valid.items())[:4]):
            with cols[i % 4]:
                chg = info.get("change_pct")
                color = "🟢" if chg and chg > 0 else "🔴" if chg and chg < 0 else "⚪"
                st.metric(
                    label=f"{ticker}",
                    value=f"{info['price']:,.1f} {info['currency']}" if info.get("price") else "N/A",
                    delta=f"{chg:.2f}%" if chg else None,
                )

    st.markdown("---")

    # 銘柄ごとの詳細 + AI分析
    for ticker in stocks:
        info = portfolio_data.get(ticker)
        with st.expander(f"**{ticker}**　{info['name'] if info else ''}", expanded=False):
            if not info:
                st.warning("データを取得できませんでした")
                continue

            # 指標
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("現在値", f"{info['price']:,.1f}" if info.get("price") else "N/A")
            c2.metric("前日比", f"{info['change_pct']:.2f}%" if info.get("change_pct") else "N/A")
            c3.metric("PER", f"{info['per']:.1f}" if info.get("per") else "N/A")
            c4.metric("PBR", f"{info['pbr']:.2f}" if info.get("pbr") else "N/A")
            c5.metric("アナリスト", info.get("analyst") or "N/A")

            w52h = info.get("week52_high")
            w52l = info.get("week52_low")
            if w52h and w52l:
                st.caption(f"52週レンジ：{w52l:,.1f} 〜 {w52h:,.1f} {info['currency']}")

            st.markdown("---")

            # 最新ニュース
            news = get_news(ticker)
            if news:
                st.markdown("**最新ニュース**")
                for n in news[:3]:
                    st.markdown(f"- {n['title']}")

            # AI分析ボタン
            api_key = st.session_state.get("api_key", "")
            if not api_key:
                st.info("🔑 左サイドバーにClaude APIキーを入力するとAI分析が使えます")
            else:
                if st.button("🤖 AI分析を実行", key=f"ai_{ticker}"):
                    with st.spinner("Geminiが分析中..."):
                        try:
                            result = analyze_with_gemini(api_key, ticker, info["name"], info, news)
                            st.session_state[f"analysis_{ticker}"] = result
                        except Exception as e:
                            st.error(f"分析に失敗しました: {e}")

            if f"analysis_{ticker}" in st.session_state:
                st.markdown(st.session_state[f"analysis_{ticker}"])
