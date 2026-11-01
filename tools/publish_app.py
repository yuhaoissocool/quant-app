"""把每日虛擬交易的資料加密成 data.enc.json（給 GitHub Pages 上的 App 讀）。

用法：python tools/publish_app.py <equity.json> <book.json> <輸出 data.enc.json>
密碼：環境變數 APP_PASSWORD（App 第一次打開時輸入同一組）
加密：PBKDF2-HMAC-SHA256（25 萬次）→ AES-256-GCM，瀏覽器用 WebCrypto 解密。
"""
import base64, json, os, sys
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITER = 250_000


def main():
    pw = os.environ.get("APP_PASSWORD")
    if not pw:
        sys.exit("缺少 APP_PASSWORD")
    eq = json.load(open(sys.argv[1]))
    book = json.load(open(sys.argv[2]))
    payload = {"equity": eq, "book": book,
               "generated": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="minutes")}
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, ensure_ascii=False).encode(), None)
    b64 = lambda x: base64.b64encode(x).decode()
    json.dump({"v": 1, "iter": ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}, open(sys.argv[3], "w"))
    print("已加密：", sys.argv[3], len(ct), "bytes")


if __name__ == "__main__":
    main()
