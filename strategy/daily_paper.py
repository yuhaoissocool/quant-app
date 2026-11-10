diff --git a/strategy/daily_paper.py b/strategy/daily_paper.py
index dfff9ae..7bb09a2 100644
--- a/strategy/daily_paper.py
+++ b/strategy/daily_paper.py
@@ -84,30 +84,101 @@ def universe(fm_headers):
     return names
 
 
-def load_prices(tickers, start, end):
-    import yfinance as yf
-    out = {}
-    for i in range(0, len(tickers), 100):
-        chunk = tickers[i:i + 100]
+PRIORITY = ["0050.TW"]          # 先抓：沒有 0050 整天就跑不了
+RETRY_WAITS = [120, 300, 600]   # 被 Yahoo 限流時，等這麼多秒後再補抓沒抓到的（限流通常幾分鐘會解除）
+
+
+class _RateLimitFlag:
+    """yfinance 批次下載被限流時不會丟例外，只會寫 log；用這個從 log 裡認出來。"""
+    def __init__(self):
+        import logging
+        self.hit = False
+        flag = self
+
+        class H(logging.Handler):
+            def emit(self, rec):
+                m = rec.getMessage()
+                if "RateLimit" in m or "Too Many Requests" in m:
+                    flag.hit = True
+        self.h = H()
+        logging.getLogger("yfinance").addHandler(self.h)
+
+    def close(self):
+        import logging
+        logging.getLogger("yfinance").removeHandler(self.h)
+
+
+def _yf_chunk(yf, chunk, start, end, out):
+    """抓一批，成功的放進 out。回傳 (這批沒抓到的, 是否被限流)。"""
+    flag = _RateLimitFlag()
+    df, limited = None, False
+    try:
         for attempt in range(3):
             try:
                 df = yf.download(chunk, start=start, end=end, auto_adjust=False, group_by="ticker",
                                  progress=False, threads=True)
                 break
             except Exception as e:
-                print("yfinance 重試", e); time.sleep(10)
+                print("yfinance 重試", str(e)[:200])
+                if "RateLimit" in type(e).__name__ or "Too Many" in str(e):
+                    limited = True
+                time.sleep(10 * (attempt + 1))
+    finally:
+        flag.close()
+    limited = limited or flag.hit or df is None
+    missing = []
+    for t in chunk:
+        try:
+            d = df[t] if len(chunk) > 1 else df
+            if isinstance(d.columns, pd.MultiIndex):     # 單檔時新版 yfinance 也可能回多層欄位
+                lv = 0 if t in d.columns.get_level_values(0) else 1
+                d = d.droplevel(lv, axis=1)
+            d = d[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
+        except Exception:
+            missing.append(t); continue
+        d = d[d.Volume > 0]
+        if len(d):
+            out[t] = d
         else:
-            continue
-        for t in chunk:
-            try:
-                d = df[t] if len(chunk) > 1 else df
-                d = d[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
-            except KeyError:
-                continue
-            d = d[d.Volume > 0]
-            if len(d):
-                out[t] = d
-        time.sleep(1)
+            missing.append(t)
+    return missing, limited
+
+
+def load_prices(tickers, start, end):
+    """0050 先單獨抓；之後如果有哪一批被限流，等一陣子再把那幾批沒抓到的補抓一次（最多 3 輪）。
+    下市、停牌的股票（平常就有一兩百檔）本來就抓不到，不會為了它們重抓。"""
+    import yfinance as yf
+    out = {}
+    first = [t for t in PRIORITY if t in tickers]
+    rest = [t for t in dict.fromkeys(tickers) if t not in first]
+    retry = []
+    for t in first:
+        miss, lim = _yf_chunk(yf, [t], start, end, out)
+        if miss:
+            retry += miss          # 0050 沒到一定要補
+        time.sleep(2)
+    for i in range(0, len(rest), 100):
+        miss, lim = _yf_chunk(yf, rest[i:i + 100], start, end, out)
+        if lim:
+            retry += miss
+        time.sleep(2)
+    for rnd, wait in enumerate(RETRY_WAITS, 1):
+        if not retry:
+            break
+        print(f"Yahoo 限流或 0050 沒抓到：{len(retry)} 檔待補（0050 {'有' if '0050.TW' in out else '沒有'}），"
+              f"等 {wait} 秒後第 {rnd} 次補抓")
+        time.sleep(wait)
+        todo, retry = retry, []
+        todo = [t for t in first if t in todo] + [t for t in todo if t not in first]
+        if todo and todo[0] in first:
+            miss, lim = _yf_chunk(yf, [todo[0]], start, end, out)
+            retry += miss; todo = todo[1:]
+        for i in range(0, len(todo), 100):
+            miss, lim = _yf_chunk(yf, todo[i:i + 100], start, end, out)
+            if lim:
+                retry += miss
+            time.sleep(2)
+    print(f"Yahoo 股價：抓到 {len(out)} 檔，0050 {'有' if '0050.TW' in out else '沒有'}")
     return out
 
 
@@ -460,7 +531,7 @@ def main():
     if cache and os.path.exists(cache):
         px = {t: d.loc[:pd.Timestamp(today)] for t, d in pd.read_pickle(cache).items()}
     else:
-        px = load_prices(tickers + ["0050.TW"], (today - timedelta(days=560)).isoformat(),
+        px = load_prices(["0050.TW"] + tickers,(today - timedelta(days=560)).isoformat(),
                          (max(today, datetime.now(TW).date()) + timedelta(days=1)).isoformat())
         if cache:
             pd.to_pickle(px, cache)
