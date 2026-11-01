"""每日虛擬交易：三條路線同時跑
=================================================
三條路線各 10 萬：A＝只跑改良突破；B＝只跑月換股；A+B＝5 萬突破＋5 萬月換股
A 改良突破（最多 3 檔）
  訊號  收盤突破過去 250 日最高價（前一天還沒突破），量 > 20 日均量 2 倍，
        20 日平均成交金額 ≥ 5,000 萬，股價 ≥ 10
  營收  最新已公布月營收（次月 10 日後才算公布）創 24 個月新高，且 YoY > 20%
  進場  隔天開盤價，開盤需介於前高 +2%～+10%，否則換下一名（多檔時 60 日強度高的優先）
  出場  收盤 < 前高×0.97、收盤 < 20 日線、或持有滿 60 個交易日 → 隔天開盤賣
B 月換股（5 檔）
  每月 11 日（含）之後第一個交易日收盤後決定：
  條件  營收創 24 個月新高且 YoY > 20%、收盤 > 50 日線、20 日均成交金額 ≥ 5,000 萬、股價 ≥ 10
  排名  60 日相對 0050 強度最高的 5 檔；隔天開盤賣掉不在名單的、買進新進榜的（每檔約帳戶 1/5）
成本    買 0.1425% + 滑價 0.1%；賣 0.1425% + 證交稅 0.3% + 滑價 0.1%
價格    yfinance 未還原價

用法：python daily_paper.py --state state.json [--post] [--asof YYYY-MM-DD]
密鑰：環境變數 DISCORD_WEBHOOK、FINMIND_TOKEN（選用）
"""
import argparse, json, math, os, sys, time
from datetime import date, datetime, timedelta, timezone
import numpy as np, pandas as pd, requests



BUY_COST = 0.001425 + 0.001
SELL_COST = 0.001425 + 0.003 + 0.001
LOOKBACK = 250
TW = timezone(timedelta(hours=8))
FM_URL = "https://api.finmindtrade.com/api/v4/data"


def secret(env, fname):
    v = os.environ.get(env)
    if v:
        return v.strip()
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
    if os.path.exists(p):
        return open(p).read().strip()
    p = fname
    return open(p).read().strip() if os.path.exists(p) else None


# ---------------- 資料 ----------------
def universe(fm_headers):
    """回傳 {ticker: 名稱}"""
    names = {}
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=30).json()
        for d in r:
            if len(d["Code"]) == 4 and d["Code"][0] != "0":
                names[d["Code"] + ".TW"] = d["Name"]
    except Exception as e:
        print("上市清單失敗：", e)
    try:
        r = requests.get(FM_URL, params={"dataset": "TaiwanStockInfo"}, headers=fm_headers, timeout=60).json()["data"]
        for d in r:
            sid = d["stock_id"]
            if len(sid) == 4 and sid.isdigit() and sid[0] != "0":
                if d["type"] == "tpex":
                    names[sid + ".TWO"] = d["stock_name"]
                elif d["type"] == "twse" and sid + ".TW" not in names:
                    names[sid + ".TW"] = d["stock_name"]
    except Exception as e:
        print("FinMind 清單失敗：", e)
    if len(names) < 500:
        sys.exit("股票清單抓取失敗")
    return names


def load_prices(tickers, start, end):
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        for attempt in range(3):
            try:
                df = yf.download(chunk, start=start, end=end, auto_adjust=False, group_by="ticker",
                                 progress=False, threads=True)
                break
            except Exception as e:
                print("yfinance 重試", e); time.sleep(10)
        else:
            continue
        for t in chunk:
            try:
                d = df[t] if len(chunk) > 1 else df
                d = d[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
            except KeyError:
                continue
            d = d[d.Volume > 0]
            if len(d):
                out[t] = d
        time.sleep(1)
    return out


def revenue_ok(sid, asof, fm_headers):
    """回傳 (是否通過, yoy, 營收月份字串)。只用 asof 當天已公布的月營收。"""
    start = (asof - timedelta(days=365 * 3 + 60)).isoformat()
    for _ in range(3):
        try:
            r = requests.get(FM_URL, params={"dataset": "TaiwanStockMonthRevenue", "data_id": sid,
                                             "start_date": start}, headers=fm_headers, timeout=60).json()
            break
        except Exception:
            time.sleep(10)
    else:
        return None, None, None
    if r.get("msg") != "success":
        print("FinMind 失敗：", sid, r.get("msg"))
        return None, None, None
    d = pd.DataFrame(r.get("data", []))
    if d.empty:
        return False, None, None
    d["avail"] = pd.to_datetime(d.date) + pd.Timedelta(days=10)
    d = d[d.avail <= pd.Timestamp(asof)]
    d["ym"] = d.revenue_year * 12 + d.revenue_month
    d = d.drop_duplicates("ym").sort_values("ym").set_index("ym")
    if d.empty:
        return False, None, None
    full = d.reindex(range(d.index.min(), d.index.max() + 1))
    rev = full.revenue
    last = rev.index[-1]
    if len(rev) < 25 or pd.isna(rev.iloc[-1]) or pd.isna(rev.get(last - 12)):
        return False, None, None
    yoy = rev.iloc[-1] / rev[last - 12] - 1
    high24 = rev.iloc[-1] >= rev.iloc[-24:].max()
    ym = f"{int(full.revenue_year.iloc[-1])}/{int(full.revenue_month.iloc[-1]):02d}"
    return bool(high24 and yoy > 0.2), float(yoy), ym




# ---------------- 帳戶共用 ----------------
LINES = {   # 子帳戶
    "A": {"name": "A 改良突破", "type": "A", "capital": 100_000, "slots": 3, "route": "A"},
    "B": {"name": "B 月換股", "type": "B", "capital": 100_000, "slots": 5, "route": "B"},
    "AB_A": {"name": "A+B 的突破部分", "type": "A", "capital": 50_000, "slots": 3, "route": "A+B"},
    "AB_B": {"name": "A+B 的月換股部分", "type": "B", "capital": 50_000, "slots": 5, "route": "A+B"},
}
ROUTES = {"A": ["A"], "B": ["B"], "A+B": ["AB_A", "AB_B"]}


def new_acct(k):
    return {"capital": LINES[k]["capital"], "cash": LINES[k]["capital"], "positions": [], "pending_buy": [],
            "pending_sell": [], "trades": [], "last_reb": None}


def code(t):
    return t.split(".")[0]


def acct_value(ac, price_of):
    return ac["cash"] + sum(p["shares"] * price_of(p) for p in ac["positions"])


FILLS = []   # 給表格圖用的結構化成交紀錄


def fill_orders(ac, k, bar, today, events):
    """用今天開盤成交昨天排好的委託。"""
    slots = LINES[k]["slots"]
    for s in ac["pending_sell"]:
        p = next((x for x in ac["positions"] if x["ticker"] == s["ticker"]), None)
        if p is None:
            continue
        b = bar(s["ticker"])
        if b is None:
            events.append(f"⚠️ {code(p['ticker'])} {p['name']} 今天沒有成交資料，賣單順延"); continue
        price = float(b.Open)
        cash_in = p["shares"] * price * (1 - SELL_COST)
        cost = p["shares"] * p["entry"] * (1 + BUY_COST)
        ret = cash_in / cost - 1
        ac["cash"] += cash_in
        ac["positions"].remove(p)
        ac["trades"].append({"ticker": p["ticker"], "name": p["name"], "entry_date": p["entry_date"],
                             "entry": p["entry"], "exit_date": today.isoformat(), "exit": round(price, 2),
                             "shares": p["shares"], "pnl": round(cash_in - cost), "ret": round(ret, 4),
                             "reason": s["reason"]})
        FILLS.append({"k": k, "act": "賣出", "code": code(p["ticker"]), "name": p["name"], "shares": p["shares"],
                      "price": price, "ret": ret, "note": s["reason"]})
        events.append(f"🔴 賣出 {code(p['ticker'])} {p['name']} {p['shares']} 股 @ {price:.2f}"
                      f"（{s['reason']}），報酬 {ret:+.1%}，損益 {cash_in - cost:+,.0f}")
    ac["pending_sell"] = [s for s in ac["pending_sell"] if any(p["ticker"] == s["ticker"] for p in ac["positions"])]

    def px_open(p):
        b = bar(p["ticker"])
        return float(b.Open) if b is not None else p["last_close"]

    for c in ac["pending_buy"]:
        if len(ac["positions"]) >= slots:
            events.append(f"⏭️ {code(c['ticker'])} {c['name']}：已滿 {slots} 檔，不買"); continue
        if any(p["ticker"] == c["ticker"] for p in ac["positions"]):
            continue
        b = bar(c["ticker"])
        if b is None:
            events.append(f"⏭️ {code(c['ticker'])} {c['name']}：今天沒有成交資料"); continue
        o = float(b.Open)
        if LINES[k]["type"] == "A":
            gap = o / c["prior_high"] - 1
            if gap < 0.02 or gap > 0.10:
                FILLS.append({"k": k, "act": "跳過", "code": code(c["ticker"]), "name": c["name"], "shares": None,
                              "price": o, "ret": None, "note": f"開盤離前高 {gap:+.1%}，需介於 +2%～+10%"})
                events.append(f"⏭️ {code(c['ticker'])} {c['name']}：開盤 {o:.2f} 離前高 {c['prior_high']:.2f} {gap:+.1%}"
                              f"（需介於 +2%～+10%），不買")
                continue
        amt = min(acct_value(ac, px_open) / slots, ac["cash"])
        shares = int(amt / (o * (1 + BUY_COST)))
        if shares <= 0:
            events.append(f"⏭️ {code(c['ticker'])} {c['name']}：現金不足"); continue
        ac["cash"] -= shares * o * (1 + BUY_COST)
        pos = {"ticker": c["ticker"], "name": c["name"], "entry_date": today.isoformat(), "entry": round(o, 2),
               "shares": shares, "signal_date": c["signal_date"], "last_close": o}
        if LINES[k]["type"] == "A":
            pos.update({"prior_high": c["prior_high"], "stop": round(c["prior_high"] * 0.97, 2)})
        ac["positions"].append(pos)
        extra = f"，停損 {c['prior_high'] * 0.97:.2f}" if LINES[k]["type"] == "A" else ""
        FILLS.append({"k": k, "act": "買進", "code": code(c["ticker"]), "name": c["name"], "shares": shares,
                      "price": o, "ret": None, "note": (f"停損 {c['prior_high'] * 0.97:.2f}" if extra else "月換股進榜")})
        events.append(f"🟢 買進 {code(c['ticker'])} {c['name']} {shares} 股 @ {o:.2f}（約 {shares * o:,.0f} 元{extra}）")
    ac["pending_buy"] = []


# ---------------- 表格圖片 ----------------
ROUTE_LABEL = {"A": "A", "B": "B", "AB_A": "A+B·突破", "AB_B": "A+B·月換股"}
UP, DOWN, MUTED, FG, BG, PANEL, LINE, ACC = "#ff5c5c", "#3ecf7a", "#9aa0a8", "#e8e9eb", "#232428", "#2b2d31", "#3a3c42", "#c9a6ff"


def signed_color(v):
    return MUTED if v is None or v == 0 else (UP if v > 0 else DOWN)


def render_png(path, title, subtitle, sections):
    """sections: [(標題, 欄名, 欄寬(英吋), 對齊, rows)]；rows 每格是 str 或 (str, 顏色)。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    fam = next((f.name for f in font_manager.fontManager.ttflist if "Noto Sans CJK TC" in f.name), None)
    if fam is None:
        raise RuntimeError("找不到中文字型")
    plt.rcParams["font.family"] = fam
    W, RH, pad = 11.0, 0.34, 0.35
    H = 1.0 + sum(0.55 + RH * (1 + max(1, len(sec[4]))) + 0.25 for sec in sections)
    fig = plt.figure(figsize=(W, H), dpi=150)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    ax.text(pad, 0.45, title, fontsize=17, color=FG, weight="bold", va="center")
    ax.text(pad, 0.82, subtitle, fontsize=10.5, color=MUTED, va="center")
    y = 1.15
    for head, cols, widths, aligns, rows in sections:
        ax.text(pad, y + 0.2, head, fontsize=12.5, color=ACC, weight="bold", va="center")
        y += 0.5
        tw = sum(widths)
        ax.add_patch(plt.Rectangle((pad - 0.08, y - 0.04), tw + 0.16, RH * (1 + max(1, len(rows))) + 0.08,
                                   facecolor=PANEL, edgecolor=LINE, lw=0.8))
        x = pad
        for c, w, al in zip(cols, widths, aligns):
            ax.text(x + (w - 0.1 if al == "r" else 0.05), y + RH / 2, c, fontsize=9.5, color=MUTED,
                    ha="right" if al == "r" else "left", va="center")
            x += w
        y += RH
        ax.plot([pad, pad + tw], [y, y], color=LINE, lw=0.8)
        if not rows:
            ax.text(pad + 0.05, y + RH / 2, "（無）", fontsize=10, color=MUTED, va="center")
            y += RH
        for r in rows:
            x = pad
            for cell, w, al in zip(r, widths, aligns):
                txt, col = (cell if isinstance(cell, tuple) else (cell, FG))
                ax.text(x + (w - 0.1 if al == "r" else 0.05), y + RH / 2, txt, fontsize=10, color=col,
                        ha="right" if al == "r" else "left", va="center")
                x += w
            y += RH
        y += 0.3
    fig.savefig(path, facecolor=BG)
    plt.close(fig)


def build_sections(st, report, rv, bret, today):
    pct = lambda v: (f"{v:+.2%}", signed_color(v))
    pct1 = lambda v: (f"{v:+.1%}", signed_color(v))
    secs = []
    cash = {r: sum(st["accounts"][k]["cash"] for k in ks) for r, ks in ROUTES.items()}
    npos = {r: sum(len(st["accounts"][k]["positions"]) for k in ks) for r, ks in ROUTES.items()}
    rows = [[r, f"{rv[r]:,.0f}", pct(rv[r] / 100_000 - 1), f"{cash[r]:,.0f}", str(npos[r])] for r in ROUTES]
    rows.append([("0050", MUTED), (f"{100_000 * (1 + bret):,.0f}", MUTED), pct(bret), ("—", MUTED), ("—", MUTED)])
    secs.append(("帳戶總覽（各 10 萬起）", ["路線", "資產", "累積報酬", "現金", "持股數"],
                 [1.6, 1.6, 1.4, 1.6, 1.0], ["l", "r", "r", "r", "r"], rows))
    if FILLS:
        rows = []
        for f in FILLS:
            col = UP if f["act"] == "買進" else DOWN if f["act"] == "賣出" else MUTED
            rows.append([ROUTE_LABEL[f["k"]], (f["act"], col), f"{f['code']} {f['name']}",
                         "" if f["shares"] is None else f"{f['shares']:,}", f"{f['price']:,.2f}",
                         pct1(f["ret"]) if f["ret"] is not None else "", f["note"][:22]])
        secs.append(("今天開盤成交", ["路線", "動作", "股票", "股數", "價格", "報酬", "說明"],
                     [1.25, 0.6, 1.9, 0.75, 1.0, 0.85, 3.9], ["l", "l", "l", "r", "r", "r", "l"], rows))
    rows = []
    for k in LINES:
        ac = st["accounts"][k]
        sells = {s["ticker"]: s["reason"] for s in ac["pending_sell"]}
        for p in ac["positions"]:
            note = ("明天賣：" + sells[p["ticker"]]) if p["ticker"] in sells else (
                f"停損 {p['stop']:.2f}" if LINES[k]["type"] == "A" else "持有到下次換股")
            rows.append([ROUTE_LABEL[k], f"{code(p['ticker'])} {p['name']}", f"{p['shares']:,}", f"{p['entry']:,.2f}",
                         f"{p['last_close']:,.2f}", pct1(p["last_close"] / p["entry"] - 1),
                         (note[:22], DOWN if p["ticker"] in sells else MUTED)])
    secs.append(("目前持股", ["路線", "股票", "股數", "成本", "現價", "報酬", "備註"],
                 [1.25, 1.9, 0.75, 1.0, 1.0, 0.85, 3.5], ["l", "l", "r", "r", "r", "r", "l"], rows))
    rows = []
    for k in LINES:
        ac = st["accounts"][k]
        for s in ac["pending_sell"]:
            p = next(x for x in ac["positions"] if x["ticker"] == s["ticker"])
            rows.append([ROUTE_LABEL[k], ("賣出", DOWN), f"{code(p['ticker'])} {p['name']}", f"{p['shares']:,} 股", s["reason"][:24]])
        for n, c in enumerate(ac["pending_buy"], 1):
            label = "候選" if LINES[k]["type"] == "A" else "買進"
            rows.append([ROUTE_LABEL[k], (f"{label}{n}" if label == "候選" else label, UP),
                         f"{code(c['ticker'])} {c['name']}", f"收 {c['close']:,.2f}", c.get("note", "")[:42]])
    secs.append(("明天開盤要做的事", ["路線", "動作", "股票", "參考", "條件"],
                 [1.25, 0.75, 1.9, 1.2, 5.0], ["l", "l", "l", "r", "l"], rows))
    return secs



# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--post", action="store_true", help="推播到 Discord")
    ap.add_argument("--asof", help="測試用：假裝今天是這天")
    a = ap.parse_args()

    tok = secret("FINMIND_TOKEN", ".finmind_token")
    fmh = {"Authorization": "Bearer " + tok} if tok else {}
    today = date.fromisoformat(a.asof) if a.asof else datetime.now(TW).date()

    st = json.load(open(a.state)) if os.path.exists(a.state) else {}
    if st.get("version") != 3:          # 新帳戶（舊版 → 重新開始）
        st = {"version": 3, "last_run": None, "start_date": None, "bench_base": None,
              "accounts": {k: new_acct(k) for k in LINES}, "equity": [], "log": []}
    if st["last_run"] and today.isoformat() <= st["last_run"]:
        print("ALREADY_RAN 今天已經跑過了"); sys.exit(4)

    names = universe(fmh)
    tickers = sorted(names)
    cache = os.environ.get("PX_CACHE")
    if cache and os.path.exists(cache):
        px = {t: d.loc[:pd.Timestamp(today)] for t, d in pd.read_pickle(cache).items()}
    else:
        px = load_prices(tickers + ["0050.TW"], (today - timedelta(days=560)).isoformat(),
                         (today + timedelta(days=1)).isoformat())
        if cache:
            pd.to_pickle(px, cache)
    bench = px.pop("0050.TW", None)
    if bench is None or bench.index[-1].date() != today:
        print(f"NO_NEW_DATA {today} 沒有新的交易資料（休市或資料未更新），不執行"); sys.exit(3)
    T = pd.Timestamp(today)
    b_close = bench.Close

    def bar(t):
        d = px.get(t)
        return d.loc[T] if d is not None and T in d.index else None

    # ---------- 共用指標 ----------
    ind = {}
    for t, d in px.items():
        if len(d) < 200 or d.index[-1] != T:
            continue
        c, h, v = d.Close, d.High, d.Volume
        ph = h.shift(1).rolling(LOOKBACK, min_periods=200).max()
        av = v.shift(1).rolling(20, min_periods=16).mean()
        to = (c * v).shift(1).rolling(20, min_periods=16).mean()
        bb = b_close.reindex(c.index).ffill()
        ind[t] = {"close": float(c.iloc[-1]), "ph": float(ph.iloc[-1]), "ph_prev": float(ph.iloc[-2]),
                  "prev_close": float(c.iloc[-2]),
                  "vol_ratio": float(v.iloc[-1] / av.iloc[-1]) if av.iloc[-1] > 0 else 0.0,
                  "turn20": float(to.iloc[-1]), "ma20": float(c.iloc[-20:].mean()), "ma50": float(c.iloc[-50:].mean()),
                  "rs60": float((c.iloc[-1] / c.iloc[-61]) / (bb.iloc[-1] / bb.iloc[-61]) - 1)}

    # ---------- 1. 用今天開盤成交昨天的委託 ----------
    events = {k: [] for k in LINES}
    for k in LINES:
        fill_orders(st["accounts"][k], k, bar, today, events[k])
        for p in st["accounts"][k]["positions"]:
            if p["ticker"] in ind:
                p["last_close"] = ind[p["ticker"]]["close"]

    # ---------- 2. A 型：今天的突破訊號（算一次，A 和 A+B 共用）----------
    cands = []
    for t, x in ind.items():
        if (x["close"] > x["ph"] and x["prev_close"] <= x["ph_prev"] and x["vol_ratio"] > 2.0
                and x["turn20"] >= 5e7 and x["close"] >= 10):
            cands.append({"ticker": t, "name": names.get(t, ""), "prior_high": round(x["ph"], 2),
                          "close": x["close"], "vol_ratio": x["vol_ratio"], "rs60": x["rs60"]})
    passedA, rejectedA, failedA = [], [], []
    for c in sorted(cands, key=lambda z: -z["rs60"]):
        ok, yoy, ym = revenue_ok(code(c["ticker"]), today, fmh)
        c.update({"rev_yoy": yoy, "rev_month": ym, "signal_date": today.isoformat()})
        if ok:
            c["note"] = (f"開盤 {c['prior_high'] * 1.02:.2f}～{c['prior_high'] * 1.10:.2f} 才買"
                         f"｜量 {c['vol_ratio']:.1f} 倍｜營收 YoY {yoy:+.0%}")
        (failedA if ok is None else passedA if ok else rejectedA).append(c)
        time.sleep(0.5)
    notesA = [f"今日突破且量>2倍 {len(cands)} 檔，通過營收篩選 {len(passedA)} 檔"
              + (f"；未通過：{', '.join(code(c['ticker']) + c['name'] for c in rejectedA[:6])}" if rejectedA else "")]
    if failedA:
        notesA.append(f"⚠️ {len(failedA)} 檔抓不到月營收，今天略過：" + ", ".join(code(c['ticker']) + c['name'] for c in failedA[:6]))

    # ---------- 3. B 型：本月名單（換股日才算一次，B 和 A+B 共用）----------
    ym_now = f"{today.year}-{today.month:02d}"
    need_reb = today.day >= 11 and any(st["accounts"][k]["last_reb"] != ym_now for k in LINES if LINES[k]["type"] == "B")
    targetB, notesB = None, []
    if need_reb:
        pool = sorted([(t, x) for t, x in ind.items() if x["turn20"] >= 5e7 and x["close"] >= 10
                       and x["close"] > x["ma50"]], key=lambda z: -z[1]["rs60"])
        target, checked, failed = [], 0, 0
        for t, x in pool:
            if len(target) >= 5 or checked >= 150:
                break
            ok, yoy, rym = revenue_ok(code(t), today, fmh)
            checked += 1
            if ok is None:
                failed += 1
            elif ok:
                target.append({"ticker": t, "name": names.get(t, ""), "close": x["close"], "rs60": x["rs60"],
                               "rev_yoy": yoy, "rev_month": rym, "signal_date": today.isoformat(),
                               "note": f"60日強度 {x['rs60']:+.0%}｜營收 {rym} YoY {yoy:+.0%}"})
            time.sleep(0.4)
        if failed > checked / 2:
            notesB.append(f"⚠️ 月營收抓取失敗太多（{failed}/{checked}），本月換股延到明天再試")
        else:
            targetB = target
            notesB.append("📅 今天是本月換股日。本月名單：" + "、".join(f"{code(c['ticker'])}{c['name']}" for c in target))
    elif LINES and today.day < 11:
        notesB.append("非換股日，續抱。下次換股：本月 11 日之後第一個交易日收盤後決定")
    else:
        notesB.append("非換股日，續抱。下次換股：下個月 11 日之後第一個交易日收盤後決定")

    # ---------- 4. 各子帳戶套用 ----------
    report = {}
    for k in LINES:
        ac = st["accounts"][k]; holds, todo = [], []
        ac["pending_sell"] = []
        if LINES[k]["type"] == "A":
            for p in ac["positions"]:
                d = px.get(p["ticker"])
                if d is None or T not in d.index:
                    holds.append(f"• {code(p['ticker'])} {p['name']}：今天無資料"); continue
                c = float(d.Close.loc[T]); ma20 = float(d.Close.loc[:T].iloc[-20:].mean())
                held = int(((d.index >= pd.Timestamp(p["entry_date"])) & (d.index <= T)).sum())
                reason = ("停損：收盤跌破前高 3%" if c < p["prior_high"] * 0.97 else
                          "出場：收盤跌破 20 日線" if c < ma20 else "出場：持有滿 60 天" if held >= 60 else None)
                holds.append(f"• {code(p['ticker'])} {p['name']} {p['shares']} 股｜成本 {p['entry']:.2f} → 收 {c:.2f}"
                             f"（{c / p['entry'] - 1:+.1%}）｜停損 {p['stop']:.2f}｜20MA {ma20:.2f}｜第 {held} 天")
                if reason:
                    ac["pending_sell"].append({"ticker": p["ticker"], "reason": reason})
            held_after = {p["ticker"] for p in ac["positions"]} - {s["ticker"] for s in ac["pending_sell"]}
            ac["pending_buy"] = [dict(c) for c in passedA if c["ticker"] not in held_after]
            free = LINES[k]["slots"] - len(held_after)
            todo += [f"🔴 賣 {code(s['ticker'])} {next(p['name'] for p in ac['positions'] if p['ticker'] == s['ticker'])}（{s['reason']}）"
                     for s in ac["pending_sell"]]
            if ac["pending_buy"]:
                todo.append(f"🟢 候選（空位 {free} 個，依序買；開盤需介於前高 +2%～+10%）：")
                todo += [f"  {n}. {code(c['ticker'])} {c['name']}｜收 {c['close']:.2f}｜{c['note']}"
                         for n, c in enumerate(ac["pending_buy"][:6], 1)]
        else:
            for p in ac["positions"]:
                holds.append(f"• {code(p['ticker'])} {p['name']} {p['shares']} 股｜成本 {p['entry']:.2f} → 收 {p['last_close']:.2f}"
                             f"（{p['last_close'] / p['entry'] - 1:+.1%}）")
            if targetB is not None and ac["last_reb"] != ym_now:
                ac["last_reb"] = ym_now
                tset = {c["ticker"] for c in targetB}
                ac["pending_sell"] = [{"ticker": p["ticker"], "reason": "月換股：本月不在前 5 名"}
                                      for p in ac["positions"] if p["ticker"] not in tset]
                held = {p["ticker"] for p in ac["positions"]}
                ac["pending_buy"] = [dict(c) for c in targetB if c["ticker"] not in held]
                todo += [f"🔴 賣 {code(s['ticker'])} {next(p['name'] for p in ac['positions'] if p['ticker'] == s['ticker'])}（{s['reason']}）"
                         for s in ac["pending_sell"]]
                todo += [f"🟢 買 {code(c['ticker'])} {c['name']}｜收 {c['close']:.2f}｜{c['note']}" for c in ac["pending_buy"]]
                keep = [p for p in ac["positions"] if p["ticker"] in tset]
                if keep:
                    todo.append("續抱：" + "、".join(code(p["ticker"]) + p["name"] for p in keep))
            else:
                ac["pending_buy"] = []
        report[k] = {"holds": holds, "todo": todo, "value": acct_value(ac, lambda p: p["last_close"])}

    # ---------- 5. 資產 ----------
    bclose = float(b_close.iloc[-1])
    if st["bench_base"] is None:
        st["bench_base"] = bclose; st["start_date"] = today.isoformat()
    rv = {r: sum(report[k]["value"] for k in ks) for r, ks in ROUTES.items()}
    st["equity"].append({"date": today.isoformat(), **{r: round(v) for r, v in rv.items()},
                         "bench": round(100_000 * bclose / st["bench_base"])})
    st["last_run"] = today.isoformat()
    st["log"].append({"date": today.isoformat(), "events": events, "notesA": notesA, "notesB": notesB})
    st["log"] = st["log"][-120:]
    json.dump(st, open(a.state, "w"), ensure_ascii=False, indent=1)

    # ---------- 6. 訊息 ----------
    bret = bclose / st["bench_base"] - 1
    L = [f"📈 **虛擬交易日報 {today}**（三條路線各 10 萬起）",
         "　".join(f"**{r}** {v:,.0f}（{v / 100_000 - 1:+.2%}）" for r, v in rv.items()) + f"　0050 {bret:+.2%}"]
    for k in ["A", "B"]:
        r = report[k]; ac = st["accounts"][k]
        L += ["", f"━━ **{LINES[k]['name']}**｜現金 {ac['cash']:,.0f}"]
        if events[k]:
            L += ["今天開盤成交："] + events[k]
        L += [f"持股（{len(ac['positions'])}/{LINES[k]['slots']}）："] + (r["holds"] or ["（空手）"])
        L += ["明天開盤："] + (r["todo"] or ["沒有動作"])
        L += notesA if k == "A" else notesB
    L += ["", "━━ **A+B**（5 萬突破＋5 萬月換股，訊號同上，股數減半）"]
    for k in ROUTES["A+B"]:
        ac = st["accounts"][k]
        if events[k]:
            L += events[k]
        L.append(f"{LINES[k]['name']}：{report[k]['value']:,.0f}｜持股 " +
                 ("、".join(f"{code(p['ticker'])}{p['name']} {p['shares']} 股" for p in ac["positions"]) or "空手"))
        L += [t for t in report[k]["todo"] if t.startswith("🔴")]
    msg = "\n".join(L)
    print(msg)

    # ---------- 7. 網頁資料 ----------
    outdir = os.path.dirname(os.path.abspath(a.state))
    json.dump(st["equity"], open(os.path.join(outdir, "equity.json"), "w"), ensure_ascii=False)
    book = []
    for k in LINES:
        ac = st["accounts"][k]; route = LINES[k]["route"]
        part = "" if route != "A+B" else ("（突破）" if LINES[k]["type"] == "A" else "（月換股）")
        for p in ac["positions"]:
            sell = next((s["reason"] for s in ac["pending_sell"] if s["ticker"] == p["ticker"]), None)
            book.append({"id": f"{k}-pos-{p['ticker']}", "line": route + part, "kind": "持股", "code": code(p["ticker"]),
                         "name": p["name"], "date": p["entry_date"], "entry": p["entry"],
                         "price": round(p["last_close"], 2), "shares": p["shares"],
                         "ret": round(p["last_close"] / p["entry"] - 1, 4),
                         "note": (f"明天開盤賣（{sell}）" if sell else
                                  (f"停損 {p['stop']:.2f}" if LINES[k]["type"] == "A" else "持有到下次換股"))})
        for n, c in enumerate(ac["pending_buy"]):
            book.append({"id": f"{k}-buy-{c['ticker']}", "line": route + part, "kind": "明日候選", "code": code(c["ticker"]),
                         "name": c["name"], "date": c["signal_date"], "entry": None, "price": round(c["close"], 2),
                         "shares": None, "ret": None, "note": f"第 {n + 1} 順位｜{c.get('note', '')}"})
        for n, t in enumerate(ac["trades"]):
            book.append({"id": f"{k}-tr-{n}", "line": route + part, "kind": "已出場", "code": code(t["ticker"]),
                         "name": t["name"], "date": t["exit_date"], "entry": t["entry"], "price": t["exit"],
                         "shares": t["shares"], "ret": t["ret"],
                         "note": f"{t['entry_date']} 買進｜{t['reason']}｜損益 {t['pnl']:+,}"})
    json.dump(book, open(os.path.join(outdir, "book.json"), "w"), ensure_ascii=False)

    png = os.path.join(outdir, "report.png")
    try:
        render_png(png, f"虛擬交易日報 {today}", "三條路線各 10 萬虛擬資金｜A 改良突破、B 月換股、A+B 各半｜紅漲綠跌",
                   build_sections(st, report, rv, bret, today))
    except Exception as e:
        print("表格圖失敗：", e); png = None
    if a.post:
        hook = secret("DISCORD_WEBHOOK", ".discord_webhook")
        sent = False
        try:
            if png is None:
                raise RuntimeError("沒有表格圖")
            notes = notesA + [n for n in notesB if not n.startswith("非換股日")]
            content = (f"📈 **虛擬交易日報 {today}**　" + "　".join(f"{r} {v / 100_000 - 1:+.2%}" for r, v in rv.items())
                       + f"　0050 {bret:+.2%}\n" + "\n".join(notes))[:1900]
            with open(png, "rb") as fh:
                r = requests.post(hook, data={"payload_json": json.dumps({"content": content})},
                                  files={"file": ("report.png", fh, "image/png")}, timeout=60)
            print("Discord(圖)", r.status_code)
            sent = r.status_code < 300
        except Exception as e:
            print("表格圖失敗，改發文字版：", e)
        if not sent:
            chunks, cur = [], ""
            for line in msg.split("\n"):
                if len(cur) + len(line) + 1 > 1900:
                    chunks.append(cur); cur = ""
                cur += line + "\n"
            chunks.append(cur)
            for ch in chunks:
                r = requests.post(hook, json={"content": ch}, timeout=30)
                print("Discord", r.status_code)
                time.sleep(1)


if __name__ == "__main__":
    main()
