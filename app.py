# dentro de app.py
import os, json, base64
import firebase_admin
from firebase_admin import credentials, db, initialize_app

RTDB_URL = "https://reportes-intenligentes-default-rtdb.firebaseio.com/"

def init_firebase():
    if firebase_admin._apps:
        return

    # A) ENV en base64 (opcional)
    sa_b64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64")
    if sa_b64:
        try:
            data = json.loads(base64.b64decode(sa_b64))
            cred = credentials.Certificate(data)
            initialize_app(cred, {"databaseURL": RTDB_URL})
            print("[creds] usando FIREBASE_SERVICE_ACCOUNT_B64")
            return
        except Exception as e:
            raise RuntimeError(f"FIREBASE_SERVICE_ACCOUNT_B64 inválida: {e}")

    # B) ENV JSON plano (recomendado)
    sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT")
    if sa_json:
        try:
            cred = credentials.Certificate(json.loads(sa_json))
            initialize_app(cred, {"databaseURL": RTDB_URL})
            print("[creds] usando FIREBASE_SERVICE_ACCOUNT")
            return
        except Exception as e:
            raise RuntimeError(f"FIREBASE_SERVICE_ACCOUNT inválida: {e}")

    # C) Ruta a archivo (Secret File o archivo en repo)
    key_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
    if key_path and os.path.exists(key_path):
        cred = credentials.Certificate(key_path)
        initialize_app(cred, {"databaseURL": RTDB_URL})
        print(f"[creds] usando archivo: {key_path}")
        return

    raise RuntimeError("No hay credenciales: define FIREBASE_SERVICE_ACCOUNT (o *_B64) o FIREBASE_CREDENTIALS_PATH.")

init_firebase()


def check_auth(req):
    if not AUTH_TOKEN:
        return True
    hdr = req.headers.get("Authorization", "")
    return hdr.startswith("Bearer ") and (hdr.split(" ", 1)[1] == AUTH_TOKEN)

@app.route("/push_feed", methods=["POST"])
def push_feed():
    if not check_auth(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    try:
        p = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "JSON inválido"}), 400

    # normaliza llaves a minúsculas (por si viene 'REPORTE')
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
    # extras opcionales para trazas
    for extra in ("modalidad", "estudio", "fecha", "folio"):
        if p.get(extra) is not None:
            data[extra] = p[extra]

    try:
        key = db.reference(FEED_PATH).push(data).key  # SIEMPRE a /feed_estudios
        return jsonify({"ok": True, "key": key})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

if __name__ == "__main__":
    # Render usa gunicorn, pero esto sirve localmente
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
