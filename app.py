# app.py — Render/Flask → Firebase RTDB (/feed_estudios)
import os, json, base64, time
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, db

# 1) Instancia de Flask PRIMERO
app = Flask(__name__)

# 2) Config
RTDB_URL = "https://reportes-intenligentes-default-rtdb.firebaseio.com/"
FEED_PATH = "/feed_estudios"
AUTH_TOKEN = os.getenv("PUSH_FEED_TOKEN")  # opcional

# 3) Init Firebase (acepta ENV JSON, ENV base64 o archivo)
def init_firebase():
    if firebase_admin._apps:
        return

    sa_b64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64")
    sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT")
    sa_path = os.getenv("FIREBASE_CREDENTIALS_PATH")

    print(f"[creds] vars presentes → "
          f"FIREBASE_SERVICE_ACCOUNT={bool(sa_json)}, "
          f"FIREBASE_SERVICE_ACCOUNT_B64={bool(sa_b64)}, "
          f"FIREBASE_CREDENTIALS_PATH={sa_path}")

    if sa_b64:
        data = json.loads(base64.b64decode(sa_b64))
        cred = credentials.Certificate(data)
        firebase_admin.initialize_app(cred, {"databaseURL": RTDB_URL})
        print("[creds] usando FIREBASE_SERVICE_ACCOUNT_B64")
        return

    if sa_json:
        cred = credentials.Certificate(json.loads(sa_json))
        firebase_admin.initialize_app(cred, {"databaseURL": RTDB_URL})
        print("[creds] usando FIREBASE_SERVICE_ACCOUNT")
        return

    if sa_path and os.path.exists(sa_path):
        cred = credentials.Certificate(sa_path)
        firebase_admin.initialize_app(cred, {"databaseURL": RTDB_URL})
        print(f"[creds] usando archivo: {sa_path}")
        return

    raise RuntimeError("No hay credenciales: define FIREBASE_SERVICE_ACCOUNT (o *_B64) o FIREBASE_CREDENTIALS_PATH.")

init_firebase()

# 4) Helpers
def check_auth(req):
    if not AUTH_TOKEN:
        return True
    hdr = req.headers.get("Authorization", "")
    return hdr.startswith("Bearer ") and hdr.split(" ", 1)[1] == AUTH_TOKEN

# 5) Rutas
@app.get("/")
def home():
    return "OK", 200

# === 🔥 NUEVO: Endpoint health check para Render ===
@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200

@app.get("/debug_env")
def debug_env():
    return jsonify({
        "FIREBASE_SERVICE_ACCOUNT_present": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT")),
        "FIREBASE_SERVICE_ACCOUNT_B64_present": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT_B64")),
        "FIREBASE_CREDENTIALS_PATH": os.getenv("FIREBASE_CREDENTIALS_PATH")
    })

@app.post("/push_feed")
def push_feed():
    if not check_auth(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        p = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "JSON inválido"}), 400

    p = { (k.lower() if isinstance(k, str) else k): v for k, v in p.items() }
    cu = p.get("codigo_unico")
    if not cu:
        return jsonify({"ok": False, "error": "codigo_unico es requerido"}), 400

    data = {
        "codigo_unico": cu,
        "estatus": p.get("estatus", "SIN REPORTE"),
        "reporte": p.get("reporte", "") or "",
        "updatedAt": int(time.time() * 1000),
    }
    for extra in ("modalidad", "estudio", "fecha", "folio"):
        if p.get(extra) is not None:
            data[extra] = p[extra]

    key = db.reference(FEED_PATH).push(data).key
    return jsonify({"ok": True, "key": key})

# 6) Local dev
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
