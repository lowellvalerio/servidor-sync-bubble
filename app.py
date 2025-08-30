# app.py — Render/Flask → Firebase RTDB (cola /feed_estudios)
# Requisitos en Render: pip install flask firebase-admin
# Opcional (recomendado): variable de entorno PUSH_FEED_TOKEN para auth de cabecera

import os, time
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, db, initialize_app

# ---------- Config ----------
RTDB_URL = "https://reportes-intenligentes-default-rtdb.firebaseio.com/"  # tu URL
SERVICE_JSON = "reportes-intenligentes-firebase-adminsdk-fbsvc-9461abcac2.json"  # ruta a tu credencial
FEED_PATH = "/feed_estudios"  # ← único destino permitido
AUTH_TOKEN = os.getenv("PUSH_FEED_TOKEN")  # opcional: define esta var en Render para seguridad

# ---------- App ----------
app = Flask(__name__)

# Inicializa Firebase Admin 1 sola vez
if not firebase_admin._apps:
    cred = credentials.Certificate(SERVICE_JSON)
    initialize_app(cred, {"databaseURL": RTDB_URL})

# ---------- Helper de Auth opcional ----------
def check_auth(req):
    if not AUTH_TOKEN:
        return True  # sin token configurado → permitir (útil en pruebas)
    hdr = req.headers.get("Authorization", "")
    if not hdr.startswith("Bearer "):
        return False
    return hdr.split(" ", 1)[1] == AUTH_TOKEN

# ---------- Endpoints ----------
@app.route("/push_feed", methods=["POST"])
def push_feed():
    # Seguridad opcional (Bearer)
    if not check_auth(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        p = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "JSON inválido"}), 400

    # Normalización de llaves (por si Bubble envía 'REPORTE' en mayúsculas)
    p_norm = { (k.lower() if isinstance(k, str) else k): v for k, v in p.items() }

    # Contrato mínimo requerido
    cu = p_norm.get("codigo_unico")
    if not cu:
        return jsonify({"ok": False, "error": "codigo_unico es requerido"}), 400

    estatus = p_norm.get("estatus", "SIN REPORTE")
    reporte = p_norm.get("reporte", "")  # ya normalizamos a minúsculas

    # Campos adicionales (no obligatorios, útiles para trazas)
    modalidad = p_norm.get("modalidad")
    estudio   = p_norm.get("estudio")
    fecha     = p_norm.get("fecha")
    folio     = p_norm.get("folio")

    # Payload final que consumirá tu listener (modo cola)
    data = {
        "codigo_unico": cu,
        "estatus": estatus,
        "reporte": reporte,
        "updatedAt": int(time.time() * 1000),
    }
    # Adjunta extras si vienen
    if modalidad is not None: data["modalidad"] = modalidad
    if estudio   is not None: data["estudio"]   = estudio
    if fecha     is not None: data["fecha"]     = fecha
    if folio     is not None: data["folio"]     = folio

    try:
        key = db.reference(FEED_PATH).push(data).key  # ← SIEMPRE push (clave auto con "-")
        return jsonify({"ok": True, "key": key})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

# ---------- Main local (Render usa WSGI) ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
