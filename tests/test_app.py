import importlib
import os
import sys
import types
import unittest


class FakeReference:
    values = {}
    pushes = []

    def __init__(self, path):
        self.path = path

    def get(self):
        return self.values.get(self.path)

    def set(self, value):
        self.values[self.path] = value

    def push(self, value):
        self.pushes.append((self.path, value))
        return types.SimpleNamespace(key=f"push-{len(self.pushes)}")


fake_db = types.ModuleType("firebase_admin.db")
fake_db.reference = lambda path: FakeReference(path)
fake_credentials = types.ModuleType("firebase_admin.credentials")
fake_credentials.Certificate = lambda value: value
fake_firebase = types.ModuleType("firebase_admin")
fake_firebase._apps = [object()]
fake_firebase.credentials = fake_credentials
fake_firebase.db = fake_db
fake_firebase.initialize_app = lambda *args, **kwargs: None

sys.modules["firebase_admin"] = fake_firebase
sys.modules["firebase_admin.credentials"] = fake_credentials
sys.modules["firebase_admin.db"] = fake_db
os.environ["PUSH_FEED_TOKEN"] = "test-token"
service = importlib.import_module("app")


class ServidorSyncBubbleTest(unittest.TestCase):
    def setUp(self):
        FakeReference.values = {
            "/ecosistemas/centro-test/dispositivos": {"equipo-1": {}}
        }
        FakeReference.pushes = []
        self.client = service.app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}
        self.identity = {
            "codigo_unico": "TEST-ESTADO-001",
            "centro_id": "centro-test",
            "email_usuario": "test@example.com",
        }

    def test_save_and_restore_structured_state(self):
        state = {
            "version": "lumbar-test-v1",
            "estudio": "radiografia_columna_lumbar",
            "selecciones": {"modulos": {"eje_lumbar": {"pathological": True}}},
        }
        save = self.client.post("/push_feed", headers=self.headers, json={
            **self.identity,
            "estado_reporte": state,
            "modalidad": "RX",
            "estudio": "RAYOS X DE COLUMNA LUMBAR",
        })
        self.assertEqual(save.status_code, 200)
        self.assertTrue(save.get_json()["estado_guardado"])
        self.assertEqual(len(FakeReference.pushes), 1)

        restore = self.client.post(
            "/recuperar_estado_reporte",
            headers=self.headers,
            json=self.identity,
        )
        self.assertEqual(restore.status_code, 200)
        self.assertEqual(restore.get_json()["estado_reporte"], state)

    def test_restore_hides_existing_state_when_email_does_not_match(self):
        self.client.post("/push_feed", headers=self.headers, json={
            **self.identity,
            "estado_reporte": {"version": "v1"},
        })
        result = self.client.post("/recuperar_estado_reporte", headers=self.headers, json={
            **self.identity,
            "email_usuario": "otro@example.com",
        })
        self.assertEqual(result.status_code, 404)

    def test_restore_returns_404_for_unknown_code(self):
        result = self.client.post(
            "/recuperar_estado_reporte",
            headers=self.headers,
            json={**self.identity, "codigo_unico": "INEXISTENTE"},
        )
        self.assertEqual(result.status_code, 404)

    def test_invalid_state_is_rejected(self):
        result = self.client.post("/push_feed", headers=self.headers, json={
            **self.identity,
            "estado_reporte": ["no", "es", "objeto"],
        })
        self.assertEqual(result.status_code, 400)


if __name__ == "__main__":
    unittest.main()
