import streamlit as st
import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime, timedelta

DATA_FILE = "stocks.json"

st.set_page_config(page_title="決算カレンダー", page_icon="📅", layout="wide")

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

        # calendarは辞書形式で返ってくる
        cal = ticker.calendar
        if cal and isinstance(cal, dict) and "Earnings Date" in cal:
            dates = cal["Earnings Date"]
            if dates:
                date_val = dates[0] if isinstance(dates, list) else dates
                if hasattr(date_val, "date"):
                    return company_name, date_val
                return company_name, pd.to_datetime(date_val).date()

        # フォールバック：earnings_dates
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

        # フォールバック：earningsTimestamp
        ts = info.get("earningsTimestamp")
        if ts:
            return company_name, pd.Timestamp(ts, unit="s").date()

        return company_name, None
    except Exception:
        return ticker_symbol, None

def parse_rakuten_csv(text):
    """楽天証券の保有資産CSVから株式ティッカーを抽出する"""
    import csv, io
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    # ヘッダー行を探す（「種別」または「区分」から始まる行）
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

        # 空・投資信託・MMFはスキップ
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
    today = datetime.today().date()
    return (date - today).days

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

# ── サイドバー：銘柄登録 ──────────────────────────────────
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

st.sidebar.text_input("ティッカーシンボル", placeholder="例: AAPL または 7203.T", key="ticker_input", on_change=add_ticker)

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

        # 文字コード自動判定
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
                st.sidebar.dataframe(
                    pd.DataFrame(tickers_found, columns=["ティッカー"]),
                    hide_index=True, height=150
                )
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
                st.sidebar.warning("銘柄が見つかりませんでした。楽天証券の保有資産CSVか確認してください")

stocks = load_stocks()
if stocks:
    st.sidebar.markdown("---")
    st.sidebar.markdown("**登録中の銘柄**")
    for s in stocks:
        col1, col2 = st.sidebar.columns([3, 1])
        col1.write(s)
        if col2.button("削除", key=f"del_{s}"):
            stocks.remove(s)
            save_stocks(stocks)
            st.rerun()

# ── メイン画面 ────────────────────────────────────────────
st.title("📅 決算カレンダー")
st.caption(f"最終更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

if not stocks:
    st.info("👈 左のサイドバーから銘柄を登録してください")
    st.stop()

# フィルター
col1, col2 = st.columns([2, 2])
with col1:
    filter_days = st.selectbox("表示期間", ["全て", "7日以内", "14日以内", "30日以内"], index=0)
with col2:
    if st.button("🔄 データ更新"):
        st.cache_data.clear()
        st.rerun()

st.markdown("---")

# データ取得
@st.cache_data(ttl=3600)
def fetch_all(tickers):
    results = []
    for t in tickers:
        name, date = get_earnings_date(t)
        results.append({"ticker": t, "name": name, "date": date, "days": days_until(date)})
    return results

with st.spinner("決算日を取得中..."):
    data = fetch_all(tuple(stocks))

# フィルタリング
if filter_days == "7日以内":
    data = [d for d in data if d["days"] is not None and 0 <= d["days"] <= 7]
elif filter_days == "14日以内":
    data = [d for d in data if d["days"] is not None and 0 <= d["days"] <= 14]
elif filter_days == "30日以内":
    data = [d for d in data if d["days"] is not None and 0 <= d["days"] <= 30]

# 並び替え：日付近い順
data_sorted = sorted(data, key=lambda x: (x["days"] is None, x["days"] if x["days"] is not None else 9999))

# サマリー
alert_count = sum(1 for d in data if d["days"] is not None and 0 <= d["days"] <= 7)
if alert_count > 0:
    st.warning(f"⚠️ 7日以内に決算がある銘柄が **{alert_count}件** あります")

# テーブル表示
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
