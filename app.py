# app.py — Render/Flask → Firebase RTDB (/ecosistemas/.../dispositivos/.../feed_estudios)
import os, json, base64, time, hashlib, hmac, re
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, db

# 1) Instancia de Flask PRIMERO
app = Flask(__name__)
CORS(app)

# 2) Config
RTDB_URL = "https://reportes-intenligentes-default-rtdb.firebaseio.com/"
AUTH_TOKEN = os.getenv("PUSH_FEED_TOKEN")  # opcional (si está seteado, exige Bearer)
MAX_ATTACHMENT_BYTES = int(os.getenv("MAX_ATTACHMENT_BYTES", str(8 * 1024 * 1024)))

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

def normalize_payload(payload):
    return {
        (key.lower() if isinstance(key, str) else key): value
        for key, value in (payload or {}).items()
    }

def report_state_key(centro_id, codigo_unico):
    """Use a Firebase-safe, non-enumerable key for a report state."""
    raw = f"{centro_id}:{codigo_unico}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def parse_report_state(value):
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("estado_reporte debe ser un objeto JSON válido") from exc
    if not isinstance(value, dict):
        raise ValueError("estado_reporte debe ser un objeto JSON")
    return value

def report_state_ref(centro_id, codigo_unico):
    key = report_state_key(centro_id, codigo_unico)
    return db.reference(f"/ecosistemas/{centro_id}/estados_reportes/{key}")

def safe_segment(value):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "").strip())
    return cleaned[:100] or "sin_centro"

def attachment_ref(centro_id, codigo_unico, tipo="esquema_prostata"):
    key = report_state_key(centro_id, codigo_unico)
    return db.reference(f"/ecosistemas/{safe_segment(centro_id)}/adjuntos_reportes/{key}/{tipo}")

def attachment_database_path(centro_id, codigo_unico, tipo="esquema_prostata"):
    key = report_state_key(centro_id, codigo_unico)
    return f"/ecosistemas/{safe_segment(centro_id)}/adjuntos_reportes/{key}/{tipo}"

def normalize_attachments(value):
    if not isinstance(value, list):
        return []
    allowed = {"tipo", "storage_path", "mime_type", "size_bytes", "sha256", "updatedAt", "download_endpoint"}
    attachments = []
    for item in value[:10]:
        if not isinstance(item, dict):
            continue
        normalized = {key: item.get(key) for key in allowed if item.get(key) not in (None, "")}
        if normalized.get("tipo") and normalized.get("storage_path"):
            attachments.append(normalized)
    return attachments

def response_parts(result):
    """Normalize a Flask view result without issuing an internal HTTP request."""
    if isinstance(result, tuple):
        response = result[0]
        status = int(result[1])
    else:
        response = result
        status = int(getattr(response, "status_code", 200))
    body = response.get_json(silent=True) if hasattr(response, "get_json") else None
    return status, body if isinstance(body, dict) else {}

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

    # normalizar llaves a lower (compat Bubble)
    p = normalize_payload(p)

    # requeridos mínimos
    cu = p.get("codigo_unico")
    email = p.get("email_usuario", "")
    if not cu or not email:
        return jsonify({"ok": False, "error": "Faltan datos requeridos (codigo_unico, email_usuario)"}), 400

    # destino (centro + device)
    centro_id = p.get("centro_id")
    device_id = p.get("device_id")  # puede venir mal, pero lo guardamos como source_device_id

    print("DEBUG centro_id/device_id =>", centro_id, device_id)

    if not centro_id:
        return jsonify({"ok": False, "error": "Falta centro_id"}), 400

    try:
        estado_reporte = parse_report_state(p.get("estado_reporte", p.get("estado")))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    # payload a difundir
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

        # para depurar: quien lo originó según Bubble
        "source_device_id": device_id,
    }
    adjuntos = normalize_attachments(p.get("adjuntos"))
    if adjuntos:
        data["adjuntos"] = adjuntos

    # 🔥 DIFUSIÓN A TODOS LOS DISPOSITIVOS REGISTRADOS DEL ECOSISTEMA
    try:
        dispositivos_ref = db.reference(f"/ecosistemas/{centro_id}/dispositivos")
        dispositivos = dispositivos_ref.get() or {}

        if not isinstance(dispositivos, dict) or len(dispositivos) == 0:
            return jsonify({
                "ok": False,
                "error": f"No hay dispositivos registrados para centro_id={centro_id}"
            }), 400

        # El estado estructurado se guarda una sola vez, separado del feed que
        # consume la aplicación local. De este modo los clientes anteriores
        # siguen funcionando y Bubble puede restaurar el estudio por codigo_unico.
        estado_guardado = False
        if estado_reporte is not None:
            report_state_ref(centro_id, cu).set({
                "codigo_unico": cu,
                "email_usuario": email,
                "centro_id": centro_id,
                "modalidad": p.get("modalidad", ""),
                "estudio": p.get("estudio", ""),
                "estado_reporte": estado_reporte,
                "updatedAt": data["updatedAt"],
                "adjuntos": adjuntos,
            })
            estado_guardado = True

        pushed = {}
        for dev_id in dispositivos.keys():
            path = f"/ecosistemas/{centro_id}/dispositivos/{dev_id}/feed_estudios"
            key = db.reference(path).push(data).key
            pushed[dev_id] = key

        return jsonify({
            "ok": True,
            "pushed": pushed,
            "estado_guardado": estado_guardado,
        }), 200

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/subir_esquema_prostata")
def subir_esquema_prostata():
    if not check_auth(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    codigo_unico = str(request.form.get("codigo_unico") or "").strip()
    centro_id = str(request.form.get("centro_id") or "").strip()
    email = str(request.form.get("email_usuario") or "").strip()
    archivo = request.files.get("archivo")
    if not codigo_unico or not centro_id or not email or archivo is None:
        return jsonify({"ok": False, "error": "Faltan datos requeridos o el archivo PNG"}), 400

    contenido = archivo.read(MAX_ATTACHMENT_BYTES + 1)
    if not contenido or len(contenido) > MAX_ATTACHMENT_BYTES:
        return jsonify({"ok": False, "error": "El esquema prostático excede el tamaño permitido"}), 413
    if archivo.mimetype != "image/png" or not contenido.startswith(b"\x89PNG\r\n\x1a\n"):
        return jsonify({"ok": False, "error": "El archivo debe ser una imagen PNG válida"}), 400

    updated_at = int(time.time() * 1000)
    digest = hashlib.sha256(contenido).hexdigest()
    database_path = attachment_database_path(centro_id, codigo_unico)
    try:
        adjunto = {
            "tipo": "esquema_prostata",
            "storage_path": f"rtdb:{database_path}",
            "mime_type": "image/png",
            "size_bytes": len(contenido),
            "sha256": digest,
            "updatedAt": updated_at,
        }
        attachment_ref(centro_id, codigo_unico).set({
            **adjunto,
            "codigo_unico": codigo_unico,
            "centro_id": centro_id,
            "email_usuario": email,
            "content_base64": base64.b64encode(contenido).decode("ascii"),
        })
        return jsonify({"ok": True, "adjunto": adjunto}), 201
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.post("/obtener_adjunto_reporte")
def obtener_adjunto_reporte():
    if not check_auth(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    try:
        p = normalize_payload(request.get_json(force=True) or {})
    except Exception:
        return jsonify({"ok": False, "error": "JSON inválido"}), 400

    codigo_unico = str(p.get("codigo_unico") or "").strip()
    centro_id = str(p.get("centro_id") or "").strip()
    email = str(p.get("email_usuario") or "").strip()
    tipo = str(p.get("tipo") or "").strip()
    if not codigo_unico or not centro_id or not email or tipo != "esquema_prostata":
        return jsonify({"ok": False, "error": "Faltan datos para recuperar el adjunto"}), 400

    try:
        saved = attachment_ref(centro_id, codigo_unico, tipo).get()
        if not isinstance(saved, dict):
            return jsonify({"ok": False, "error": "Adjunto no encontrado"}), 404
        if not hmac.compare_digest(str(saved.get("codigo_unico") or ""), codigo_unico) or not hmac.compare_digest(str(saved.get("email_usuario") or ""), email):
            return jsonify({"ok": False, "error": "Adjunto no encontrado"}), 404
        content_base64 = str(saved.get("content_base64") or "")
        if not content_base64:
            return jsonify({"ok": False, "error": "Adjunto no encontrado"}), 404
        return jsonify({
            "ok": True,
            "tipo": tipo,
            "mime_type": saved.get("mime_type", "image/png"),
            "content_base64": content_base64,
            "sha256": saved.get("sha256"),
        }), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.post("/guardar-reporte")
def guardar_reporte():
    """Compatibility endpoint formerly served by motor-guardar-reportes."""
    status, body = response_parts(push_feed())
    upstream_ok = 200 <= status < 300 and body.get("ok", True) is not False
    return jsonify({
        "ok": upstream_ok,
        "status_push_feed": status,
        "respuesta": body,
    }), status

@app.post("/recuperar-estado")
@app.post("/recuperar_estado_reporte")
def recuperar_estado_reporte():
    if not check_auth(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        p = normalize_payload(request.get_json(force=True) or {})
    except Exception:
        return jsonify({"ok": False, "error": "JSON inválido"}), 400

    cu = str(p.get("codigo_unico") or "").strip()
    centro_id = str(p.get("centro_id") or "").strip()
    email = str(p.get("email_usuario") or "").strip()
    if not cu or not centro_id or not email:
        return jsonify({
            "ok": False,
            "error": "Faltan datos requeridos (codigo_unico, centro_id, email_usuario)",
        }), 400

    try:
        saved = report_state_ref(centro_id, cu).get()
        if not isinstance(saved, dict):
            return jsonify({"ok": False, "error": "Estado no encontrado"}), 404

        saved_email = str(saved.get("email_usuario") or "")
        saved_code = str(saved.get("codigo_unico") or "")
        if not hmac.compare_digest(saved_email, email) or not hmac.compare_digest(saved_code, cu):
            # No revelar si el código existe cuando la identidad no coincide.
            return jsonify({"ok": False, "error": "Estado no encontrado"}), 404

        estado = saved.get("estado_reporte")
        if not isinstance(estado, dict):
            return jsonify({"ok": False, "error": "Estado no encontrado"}), 404

        return jsonify({
            "ok": True,
            "codigo_unico": cu,
            "estado_reporte": estado,
            "updatedAt": saved.get("updatedAt"),
        }), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

# 6) Local dev
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
