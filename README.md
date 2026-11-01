# 量化帳戶

三條路線的台股虛擬交易（A 改良突破、B 月換股、A+B 各半）。每個交易日收盤後由排程更新 `data.enc.json`。

- 資料用 AES-256-GCM 加密（金鑰由密碼經 PBKDF2-SHA256 25 萬次推導），網頁在瀏覽器內解密，伺服器上只有密文。
- 加到手機主畫面即可當 App 使用。
- `tools/publish_app.py`：把每日的 equity.json / book.json 加密成 data.enc.json。

虛擬交易紀錄，非投資建議。
