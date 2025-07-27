from flask import Flask, request, jsonify
import sqlite3
import os

app = Flask(__name__)

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

@app.route('/')
def index():
    return "Servidor de sincronización activo."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 5000))
