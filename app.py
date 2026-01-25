# app.py — Render/Flask → Firebase RTDB (/feed_estudios)
# app.py — Render/Flask → Firebase RTDB (/ecosistemas/.../dispositivos/.../feed_estudios)
import os, json, base64, time
from flask import Flask, request, jsonify
import firebase_admin
@@ -9,8 +9,7 @@

# 2) Config
RTDB_URL = "https://reportes-intenligentes-default-rtdb.firebaseio.com/"
FEED_PATH = "/feed_estudios"
AUTH_TOKEN = os.getenv("PUSH_FEED_TOKEN")  # opcional
AUTH_TOKEN = os.getenv("PUSH_FEED_TOKEN")  # opcional (si está seteado, exige Bearer)

# 3) Init Firebase (acepta ENV JSON, ENV base64 o archivo)
def init_firebase():
@@ -21,10 +20,12 @@ def init_firebase():
    sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT")
    sa_path = os.getenv("FIREBASE_CREDENTIALS_PATH")

    print(f"[creds] vars presentes → "
          f"FIREBASE_SERVICE_ACCOUNT={bool(sa_json)}, "
          f"FIREBASE_SERVICE_ACCOUNT_B64={bool(sa_b64)}, "
          f"FIREBASE_CREDENTIALS_PATH={sa_path}")
    print(
        f"[creds] vars presentes → "
        f"FIREBASE_SERVICE_ACCOUNT={bool(sa_json)}, "
        f"FIREBASE_SERVICE_ACCOUNT_B64={bool(sa_b64)}, "
        f"FIREBASE_CREDENTIALS_PATH={sa_path}"
    )

    if sa_b64:
        data = json.loads(base64.b64decode(sa_b64))
@@ -45,12 +46,15 @@ def init_firebase():
        print(f"[creds] usando archivo: {sa_path}")
        return

    raise RuntimeError("No hay credenciales: define FIREBASE_SERVICE_ACCOUNT (o *_B64) o FIREBASE_CREDENTIALS_PATH.")
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
@@ -61,7 +65,6 @@ def check_auth(req):
def home():
    return "OK", 200

# === 🔥 NUEVO: Endpoint health check para Render ===
@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200
@@ -71,38 +74,41 @@ def debug_env():
    return jsonify({
        "FIREBASE_SERVICE_ACCOUNT_present": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT")),
        "FIREBASE_SERVICE_ACCOUNT_B64_present": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT_B64")),
        "FIREBASE_CREDENTIALS_PATH": os.getenv("FIREBASE_CREDENTIALS_PATH")
    })
        "FIREBASE_CREDENTIALS_PATH": os.getenv("FIREBASE_CREDENTIALS_PATH"),
        "PUSH_FEED_TOKEN_present": bool(os.getenv("PUSH_FEED_TOKEN"))
    }), 200

@app.post("/push_feed")
def push_feed():
    # Auth
    if not check_auth(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    # JSON body
    try:
        p = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "JSON inválido"}), 400

    # normalizar llaves
    p = { (k.lower() if isinstance(k, str) else k): v for k, v in p.items() }
    # normalizar llaves a lower (compat Bubble)
    p = {(k.lower() if isinstance(k, str) else k): v for k, v in p.items()}

    # requeridos mínimos
    cu = p.get("codigo_unico")
    email = p.get("email_usuario", "")
    if not cu or not email:
        return jsonify({"ok": False, "error": "Faltan datos requeridos"}), 400
        return jsonify({"ok": False, "error": "Faltan datos requeridos (codigo_unico, email_usuario)"}), 400

    # sanitizar email
    usuario = email.replace("@", "_").replace(".", "_")

    # destino por DISPOSITIVO  
    # destino (centro + device)
    centro_id = p.get("centro_id")
    device_id = p.get("device_id")
    device_id = p.get("device_id")  # puede venir mal, pero lo guardamos como source_device_id

    print("DEBUG centro_id/device_id =>", centro_id, device_id)

    if not centro_id:
        return jsonify({"ok": False, "error": "Falta centro_id"}), 400

    # Armar payload una vez
    # payload a difundir
    data = {
        "codigo_unico": cu,
        "email_usuario": email,
@@ -113,28 +119,29 @@ def push_feed():
        "fecha": p.get("fecha", ""),
        "folio": p.get("folio", ""),
        "updatedAt": int(time.time() * 1000),

        # para depurar: quien lo originó según Bubble
        "source_device_id": device_id,
    }

    # 🔥 DIFUSIÓN A TODOS LOS DISPOSITIVOS REGISTRADOS DEL ECOSISTEMA
    try:
        # ✅ Caso A: viene device_id => push SOLO a ese dispositivo
        if device_id:
            path = f"/ecosistemas/{centro_id}/dispositivos/{device_id}/feed_estudios"
            key = db.reference(path).push(data).key
            return jsonify({"ok": True, "mode": "single", "key": key, "device_id": device_id})

        # ✅ Caso B: NO viene device_id => broadcast a TODOS los dispositivos del ecosistema
        dispositivos_ref = db.reference(f"/ecosistemas/{centro_id}/dispositivos").get() or {}
        device_ids = list(dispositivos_ref.keys())
        dispositivos_ref = db.reference(f"/ecosistemas/{centro_id}/dispositivos")
        dispositivos = dispositivos_ref.get() or {}

        if not device_ids:
            return jsonify({"ok": False, "error": "No hay dispositivos registrados en este centro_id"}), 400
        if not isinstance(dispositivos, dict) or len(dispositivos) == 0:
            return jsonify({
                "ok": False,
                "error": f"No hay dispositivos registrados para centro_id={centro_id}"
            }), 400

        pushed = {}
        for did in device_ids:
            path = f"/ecosistemas/{centro_id}/dispositivos/{did}/feed_estudios"
            pushed[did] = db.reference(path).push(data).key
        for dev_id in dispositivos.keys():
            path = f"/ecosistemas/{centro_id}/dispositivos/{dev_id}/feed_estudios"
            key = db.reference(path).push(data).key
            pushed[dev_id] = key

        return jsonify({"ok": True, "mode": "broadcast", "pushed": pushed, "count": len(pushed)})
        return jsonify({"ok": True, "pushed": pushed}), 200

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
