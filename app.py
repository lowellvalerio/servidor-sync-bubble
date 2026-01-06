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

    # normalizar llaves
    p = { (k.lower() if isinstance(k, str) else k): v for k, v in p.items() }

    cu = p.get("codigo_unico")
    email = p.get("email_usuario", "")
    if not cu or not email:
        return jsonify({"ok": False, "error": "Faltan datos requeridos"}), 400

    # sanitizar email
    usuario = email.replace("@", "_").replace(".", "_")

    # destino por DISPOSITIVO
    centro_id = p.get("centro_id")
    device_id = p.get("device_id")
    
    print("DEBUG centro_id/device_id =>", centro_id, device_id)
    
    if not centro_id or not device_id:
        return jsonify({"ok": False, "error": "Falta centro_id o device_id"}), 400
    
    path = f"/ecosistemas/{centro_id}/dispositivos/{device_id}/feed_estudios"

    data = {
        "codigo_unico": cu,
        "email_usuario": email,
        "estatus": p.get("estatus", "REPORTADO"),
        "reporte": p.get("reporte", "") or "",
        "modalidad": p.get("modalidad", ""),
        "estudio": p.get("estudio", ""),
        "fecha": p.get("fecha", ""),
        "folio": p.get("folio", ""),
        "updatedAt": int(time.time() * 1000),
    }

    try:
        key = db.reference(path).push(data).key
        return jsonify({"ok": True, "key": key})
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("🔥 FIREBASE PUSH ERROR:", repr(e))
        print(tb)
        return jsonify({
            "ok": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "trace": tb[-2000:]  # últimos 2000 chars
        }), 500

# 6) Local dev
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
