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
        # 文字コード自動判定（Shift-JIS or UTF-8）
        raw = uploaded.read()
        for enc in ["shift_jis", "utf-8", "cp932"]:
            try:
                df_csv = pd.read_csv(pd.io.common.BytesIO(raw), encoding=enc)
                break
            except Exception:
                continue

        st.sidebar.markdown("**列を選択してください**")
        cols = df_csv.columns.tolist()
        selected_col = st.sidebar.selectbox("証券コードが入っている列", cols)

        market = st.sidebar.radio("市場", ["日本株（.T を付ける）", "米国株（そのまま）"], horizontal=True)

        if st.sidebar.button("一括追加", type="primary"):
            stocks_now = load_stocks()
            added, skipped = [], []
            for val in df_csv[selected_col].dropna().astype(str):
                # 数字4桁の証券コードを抽出
                code = val.strip().split(".")[0].strip()
                if not code:
                    continue
                ticker = f"{code}.T" if "日本株" in market else code.upper()
                if ticker not in stocks_now:
                    stocks_now.append(ticker)
                    added.append(ticker)
                else:
                    skipped.append(ticker)
            save_stocks(stocks_now)
            if added:
                st.sidebar.success(f"{len(added)}銘柄を追加しました")
            if skipped:
                st.sidebar.info(f"{len(skipped)}銘柄はすでに登録済みでスキップ")
            st.rerun()

        st.sidebar.dataframe(df_csv[[selected_col]].head(5), hide_index=True)

    except Exception as e:
        st.sidebar.error(f"CSVの読み込みに失敗しました: {e}")

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
