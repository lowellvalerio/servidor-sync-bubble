# app.py — Render/Flask → Firebase RTDB (/ecosistemas/.../dispositivos/.../feed_estudios)
import os, json, base64, time
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, db

# 1) Instancia de Flask PRIMERO
app = Flask(__name__)

# 2) Config
RTDB_URL = "https://reportes-intenligentes-default-rtdb.firebaseio.com/"
AUTH_TOKEN = os.getenv("PUSH_FEED_TOKEN")  # opcional (si está seteado, exige Bearer)

# 3) Init Firebase (acepta ENV JSON, ENV base64 o archivo)
def init_firebase():
    if firebase_admin._apps:
        return

    sa_b64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64")
    sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT")
    sa_path = os.getenv("FIREBASE_CREDENTIALS_PATH")

    print(
        f"[creds] vars presentes → "
        f"FIREBASE_SERVICE_ACCOUNT={bool(sa_json)}, "
        f"FIREBASE_SERVICE_ACCOUNT_B64={bool(sa_b64)}, "
        f"FIREBASE_CREDENTIALS_PATH={sa_path}"
    )

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

    raise RuntimeError(
        "No hay credenciales: define FIREBASE_SERVICE_ACCOUNT (o *_B64) o FIREBASE_CREDENTIALS_PATH."
    )

init_firebase()

# 4) Helpers
def check_auth(req):
    # Si no hay token configurado, no exigimos auth
    if not AUTH_TOKEN:
        return True
    hdr = req.headers.get("Authorization", "")
    return hdr.startswith("Bearer ") and hdr.split(" ", 1)[1] == AUTH_TOKEN

# 5) Rutas
@app.get("/")
def home():
    return "OK", 200

@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200

@app.get("/debug_env")
def debug_env():
    return jsonify({
        "FIREBASE_SERVICE_ACCOUNT_present": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT")),
        "FIREBASE_SERVICE_ACCOUNT_B64_present": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT_B64")),
        "FIREBASE_CREDENTIALS_PATH": os.getenv("FIREBASE_CREDENTIALS_PATH"),
        "PUSH_FEED_TOKEN_present": bool(os.getenv("PUSH_FEED_TOKEN"))
    }), 200
    
@app.route("/push_feed", methods=["POST"])
def push_feed():
    if not check_auth(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    # 🔎 DEBUG
    try:
        print("=== /push_feed HIT ===")
        print("headers:", dict(request.headers))
        raw = request.get_data(as_text=True)
        print("raw_body:", raw[:2000])
        pj = request.get_json(silent=True)
        print("json_silent:", pj)
    except Exception as _e:
        print("debug error:", repr(_e))

    try:
        p = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "JSON inválido"}), 400

    # normalizar llaves
    p = {(k.lower() if isinstance(k, str) else k): v for k, v in p.items()}

    # requeridos
    cu = (p.get("codigo_unico") or "").strip()
    email = (p.get("email_usuario") or "").strip()
    centro_id = (p.get("centro_id") or "").strip()
    device_id = (p.get("device_id") or "").strip()

    if not cu or not email or not centro_id or not device_id:
        return jsonify({
            "ok": False,
            "error": "Faltan datos requeridos (codigo_unico, email_usuario, centro_id, device_id)"
        }), 400

    # sanitizar email (solo informativo)
    usuario = email.replace("@", "_").replace(".", "_")

    # clave fija para que ACTUALICE (no duplique)
    safe_cu = (cu.replace(".", "_")
                 .replace("#", "_")
                 .replace("$", "_")
                 .replace("[", "_")
                 .replace("]", "_")
                 .replace("/", "_"))

    # sanitizar device_id por si acaso
    safe_device = (device_id.replace(".", "_")
                            .replace("#", "_")
                            .replace("$", "_")
                            .replace("[", "_")
                            .replace("]", "_")
                            .replace("/", "_"))

    data = {
        "codigo_unico": cu,
        "email_usuario": email,
        "usuario_sanitizado": usuario,
        "centro_id": centro_id,
        "device_id": device_id,
        "estatus": p.get("estatus", "REPORTADO"),
        "reporte": p.get("reporte", "") or "",
        "modalidad": p.get("modalidad", ""),
        "estudio": p.get("estudio", ""),
        "fecha": p.get("fecha", ""),
        "folio": p.get("folio", ""),
        "updatedAt": int(time.time() * 1000),
    }

    try:
        root = db.reference("/")

        updates = {
            # ✅ por ecosistema
            f"ecosistemas/{centro_id}/feed_estudios/{safe_cu}": data,

            # ✅ por dispositivo (para que el listener lo vea)
            f"ecosistemas/{centro_id}/dispositivos/{safe_device}/feed_estudios/{safe_cu}": data,
        }

        root.update(updates)

        return jsonify({"ok": True, "key": safe_cu, "device_key": safe_device})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# 6) Local dev
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
