# 量化帳戶

三條路線的台股虛擬交易（A 改良突破、B 月換股、A+B 各半）。每個交易日收盤後由排程更新 `data.enc.json`。

- 資料用 AES-256-GCM 加密（金鑰由密碼經 PBKDF2-SHA256 25 萬次推導），網頁在瀏覽器內解密，伺服器上只有密文。
- 加到手機主畫面即可當 App 使用。
- `strategy/daily_paper.py`：每日虛擬交易程式（規則寫在檔案開頭）。
- `.github/workflows/daily.yml`：週一到週五收盤後由 GitHub Actions 自動執行，結果推到 Discord、更新 App。
- `state.enc.json`：加密的帳戶狀態；`tools/box.py`：加解密工具。
- 需要的 Secrets：`APP_PASSWORD`、`DISCORD_WEBHOOK`（必填）、`FINMIND_TOKEN`（選填）。

虛擬交易紀錄，非投資建議。
