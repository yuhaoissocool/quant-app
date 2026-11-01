"""加密／解密小工具（AES-256-GCM，金鑰由 APP_PASSWORD 經 PBKDF2-SHA256 推導，與 App 相同格式）。

python tools/box.py enc <明文檔> <輸出.enc.json>
python tools/box.py dec <輸入.enc.json> <明文檔>
python tools/box.py app <equity.json> <book.json> <data.enc.json>   # 給 App 讀的資料
"""
import base64, json, os, sys
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITER = 250_000
b64e = lambda x: base64.b64encode(x).decode()
b64d = base64.b64decode


def _key(pw, salt, it):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=it).derive(pw.encode())


def seal(data: bytes, pw: str) -> dict:
    salt, iv = os.urandom(16), os.urandom(12)
    return {"v": 1, "iter": ITER, "salt": b64e(salt), "iv": b64e(iv),
            "ct": b64e(AESGCM(_key(pw, salt, ITER)).encrypt(iv, data, None))}


def unseal(box: dict, pw: str) -> bytes:
    return AESGCM(_key(pw, b64d(box["salt"]), box["iter"])).decrypt(b64d(box["iv"]), b64d(box["ct"]), None)


def main():
    pw = os.environ.get("APP_PASSWORD") or sys.exit("缺少 APP_PASSWORD")
    cmd = sys.argv[1]
    if cmd == "enc":
        json.dump(seal(open(sys.argv[2], "rb").read(), pw), open(sys.argv[3], "w"))
    elif cmd == "dec":
        open(sys.argv[3], "wb").write(unseal(json.load(open(sys.argv[2])), pw))
    elif cmd == "app":
        payload = {"equity": json.load(open(sys.argv[2])), "book": json.load(open(sys.argv[3])),
                   "generated": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="minutes")}
        json.dump(seal(json.dumps(payload, ensure_ascii=False).encode(), pw), open(sys.argv[4], "w"))
    else:
        sys.exit(__doc__)
    print("ok", cmd)


if __name__ == "__main__":
    main()
