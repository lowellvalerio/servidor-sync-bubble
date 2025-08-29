import os
import sqlite3
import json
import tempfile
from flask import Flask, request, jsonify

# --- Flask ---
app = Flask(__name__)

# --- SQLite local (tu endpoint actual lo sigue usando) ---
DB_PATH = "reporte_local.db"  # Ruta de tu base de datos SQLite

@app.route('/recibir_reporte', methods=['POST'])
def recibir_reporte():
    data = request.get_json()
    codigo_unico = data.get('codigo_unico')
    contenido_reporte = data.get('REPORTE', '')
    estatus = data.get('Estatus', 'REPORTADO')

    if not codigo_unico:
        return jsonify({"error": "Falta el código único"}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE Estudios
            SET REPORTE = ?, Estatus = ?, sincronizado = 1
            WHERE codigo_unico = ?
        """, (contenido_reporte, estatus, codigo_unico))
        conn.commit()
        conn.close()
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Healthcheck simple ---
@app.route('/')
def index():
    return "Servidor de sincronización activo."

@app.route('/health')
def health():
    return jsonify({"ok": True})

# =========================
#  Firebase Admin (nuevo)
# =========================
from firebase_admin import credentials, db, initialize_app

DATABASE_URL = "https://reportes-intenligentes-default-rtdb.firebaseio.com"

# Carga segura de credencial desde variable de entorno (Render)
SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
if SERVICE_ACCOUNT_JSON:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    tmp.write(SERVICE_ACCOUNT_JSON.encode("utf-8"))
    tmp.flush()
    cred = credentials.Certificate(tmp.name)
else:
    # Alternativa local: usar archivo en disco si no hay env var
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not cred_path or not os.path.exists(cred_path):
        raise RuntimeError(
            "No hay credencial de Firebase. Define FIREBASE_SERVICE_ACCOUNT_JSON o GOOGLE_APPLICATION_CREDENTIALS"
        )
    cred = credentials.Certificate(cred_path)

initialize_app(cred, {"databaseURL": DATABASE_URL})

# Seguridad simple para llamadas desde Bubble
API_KEY_SERVER = os.environ.get("API_KEY_SERVER")  # define esto en Render
def require_api_key(req):
    return API_KEY_SERVER and req.headers.get("X-API-Key") == API_KEY_SERVER

# ===== Endpoint de eco para depurar (opcional) =====
@app.route("/api/echo", methods=["POST"])
def api_echo():
    return {"ok": True, "headers": dict(request.headers), "body": request.get_json(silent=True)}, 200

# ===== Endpoint que Bubble llamará para escribir en Firebase =====
MODALIDADES = {"CT","MR","US","DX","CR","XR","MG","NM","PT"}
ESTATUS_OK = {"SIN REPORTE","POR AUTORIZAR","REPORTADO"}

@app.route("/api/report", methods=["POST"])
def api_report():
    # Autenticación simple con API key
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    # Se espera:
    # {
    #   "instId": "COROMINAS",
    #   "paciente": {"folio":"...", "nombre":"...", "sexo":"MAS|FEM|OTRO", "edad": 30},
    #   "estudio":  {"codigo_unico":"...", "modalidad":"MR", "estudio":"IRM DE CRANEO",
    #                "fecha":"2025-08-22T12:00:00+00:00", "estatus":"SIN REPORTE", "folio":"..."}
    # }
    inst = data.get("instId")
    pac = data.get("paciente") or {}
    est = data.get("estudio") or {}

    if not inst:
        return jsonify({"ok": False, "error": "instId requerido"}), 400

    # Validaciones mínimas (alineadas con reglas de RTDB)
    for key in ("folio", "nombre", "sexo", "edad"):
        if pac.get(key) in (None, ""):
            return jsonify({"ok": False, "error": f"paciente.{key} requerido"}), 400
    if pac["sexo"] not in ("MAS", "FEM", "OTRO"):
        return jsonify({"ok": False, "error": "paciente.sexo invalido"}), 400

    for key in ("codigo_unico", "modalidad", "estudio", "fecha", "estatus", "folio"):
        if est.get(key) in (None, ""):
            return jsonify({"ok": False, "error": f"estudio.{key} requerido"}), 400
    if est["modalidad"] not in MODALIDADES:
        return jsonify({"ok": False, "error": "modalidad invalida"}), 400
    if est["estatus"] not in ESTATUS_OK:
        return jsonify({"ok": False, "error": "estatus invalido"}), 400
    if est["folio"] != pac["folio"]:
        return jsonify({"ok": False, "error": "folio de estudio != folio de paciente"}), 400

    # Escribir primero paciente (para que pase la validación del folio), luego estudio
    db.reference(f"inst/{inst}/pacientes/{pac['folio']}").update({
        "folio": pac["folio"],
        "nombre": pac["nombre"],
        "sexo": pac["sexo"],
        "edad": pac["edad"]
    })

    db.reference(f"inst/{inst}/estudios/{est['codigo_unico']}").update({
        "codigo_unico": est["codigo_unico"],
        "folio": est["folio"],
        "modalidad": est["modalidad"],
        "estudio": est["estudio"],
        "fecha": est["fecha"],
        "estatus": est["estatus"]
    })

    return jsonify({"ok": True}), 200

# --- Run ---
if __name__ == '__main__':
    # En Render usarás gunicorn; local te sirve app.run
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
