import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import fitz
from django.contrib.sessions.middleware import SessionMiddleware
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase

from . import utils
from .views import (
    _mongo_count,
    _mongo_delete_document,
    _mongo_find_one_by_id,
    _mongo_update_document,
    _datos_ajuste_firmantes,
    home_redirect,
    _indice_pendiente_actual,
    _indice_por_token,
    _indices_firmas_en_turno,
    _json_or_default,
    _obtener_hash_para_reestampado,
)


class FakeMongoCollection:
    def __init__(self, documents=None):
        self.documents = documents or []

    def _matches(self, document, query):
        for key, value in query.items():
            if isinstance(value, dict) and '$in' in value:
                if document.get(key) not in value['$in']:
                    return False
                continue
            if document.get(key) != value:
                return False
        return True

    def find_one(self, query, sort=None, projection=None):
        matches = [document for document in self.documents if self._matches(document, query)]
        if sort:
            for key, direction in reversed(sort):
                matches.sort(key=lambda document: document.get(key, 0), reverse=direction < 0)
        if not matches:
            return None
        document = matches[0]
        if projection:
            return {key: document.get(key) for key, enabled in projection.items() if enabled}
        return document

    def update_one(self, query, update):
        document = self.find_one(query)
        if document:
            document.update(update.get('$set', {}))

    def delete_one(self, query):
        document = self.find_one(query)
        if document:
            self.documents.remove(document)

    def count_documents(self, query):
        return len([document for document in self.documents if self._matches(document, query)])

    def insert_one(self, document):
        document.setdefault('_id', f"fake-{len(self.documents) + 1}")
        self.documents.append(document)


class MongoViewHelpersTest(SimpleTestCase):
    def _model(self, table_name):
        return SimpleNamespace(_meta=SimpleNamespace(db_table=table_name))

    def test_find_one_by_id_accepts_string_for_integer_id(self):
        model = self._model('motor_firmas_directoriofirmas')
        collection = FakeMongoCollection([
            {'_id': 'mongo-1', 'id': 7, 'email': 'uno@example.com'}
        ])

        with patch('motor_firmas.views._mongo_collection', return_value=collection):
            document = _mongo_find_one_by_id(model, '7')

        self.assertEqual(document.email, 'uno@example.com')

    def test_update_and_delete_use_mongo_primary_key(self):
        model = self._model('motor_firmas_directoriofirmas')
        collection = FakeMongoCollection([
            {'_id': 'mongo-1', 'id': 7, 'email': 'uno@example.com', 'notificar_celular': False}
        ])
        document = SimpleNamespace(_id='mongo-1', id=7)

        with patch('motor_firmas.views._mongo_collection', return_value=collection):
            _mongo_update_document(model, document, {'notificar_celular': True})
            self.assertEqual(_mongo_count(model, {'notificar_celular': True}), 1)
            _mongo_delete_document(model, document)

        self.assertEqual(collection.documents, [])


class MongoNotificationHelpersTest(SimpleTestCase):
    def _model(self, table_name):
        return SimpleNamespace(_meta=SimpleNamespace(db_table=table_name))

    def test_pending_notification_is_refreshed_without_duplicate(self):
        notification_model = self._model('signature_notifications')
        collection = FakeMongoCollection([
            {
                '_id': 'n1',
                'id': 1,
                'user_email': 'uno@example.com',
                'reference_id': 'LIBRE-1',
                'status': 'pending',
                'processed': False,
                'created_at': 'old',
            }
        ])

        with patch('motor_firmas.utils._mongo_collection', return_value=collection):
            utils._registrar_notificacion_pendiente(notification_model, 'uno@example.com', 'LIBRE-1')

        self.assertEqual(len(collection.documents), 1)
        self.assertNotEqual(collection.documents[0]['created_at'], 'old')

    def test_master_does_not_replace_active_signer_with_owner_notice(self):
        master_model = self._model('signatures_master')
        collection = FakeMongoCollection([
            {
                '_id': 'm1',
                'id': 1,
                'reference_id': 'LIBRE-1',
                'user_email': 'firmante@example.com',
                'status': 'pending',
                'notification_enabled': True,
                'notified_to_mobile': False,
            }
        ])

        with patch('motor_firmas.utils._mongo_collection', return_value=collection):
            utils._actualizar_registro_maestro(master_model, 'owner@example.com', 'LIBRE-1')

        self.assertEqual(collection.documents[0]['user_email'], 'firmante@example.com')
        self.assertEqual(collection.documents[0]['status'], 'pending')

    def test_master_advances_after_previous_signer_was_completed(self):
        master_model = self._model('signatures_master')
        collection = FakeMongoCollection([
            {
                '_id': 'm1',
                'id': 1,
                'reference_id': 'LIBRE-1',
                'user_email': 'firmante1@example.com',
                'status': 'signed',
                'notification_enabled': False,
                'notified_to_mobile': True,
            }
        ])

        with patch('motor_firmas.utils._mongo_collection', return_value=collection):
            utils._actualizar_registro_maestro(master_model, 'firmante2@example.com', 'LIBRE-1')

        self.assertEqual(collection.documents[0]['user_email'], 'firmante2@example.com')
        self.assertEqual(collection.documents[0]['status'], 'pending')
        self.assertTrue(collection.documents[0]['notification_enabled'])
        self.assertFalse(collection.documents[0]['notified_to_mobile'])


class SignatureTurnHelpersTest(SimpleTestCase):
    def test_json_or_default_decodes_double_serialized_values(self):
        value = '"[{\\"key\\": \\"FIRMA_1\\"}]"'

        self.assertEqual(_json_or_default(value, []), [{'key': 'FIRMA_1'}])

    def test_multiple_contiguous_signatures_same_email_share_turn(self):
        firmantes = [
            {'email': 'uno@example.com', 'token_firmante': 'a'},
            {'email': 'UNO@example.com', 'token_firmante': 'b'},
            {'email': 'dos@example.com', 'token_firmante': 'c'},
        ]
        proceso = SimpleNamespace(indice_actual=1)

        indice = _indice_pendiente_actual(proceso, firmantes)
        indices_turno = _indices_firmas_en_turno(firmantes, indice)

        self.assertEqual(indices_turno, [0, 1])
        self.assertIn(_indice_por_token(firmantes, 'b'), indices_turno)

    def test_same_email_after_other_pending_signer_shares_turn(self):
        firmantes = [
            {'email': 'uno@example.com', 'token_firmante': 'a'},
            {'email': 'dos@example.com', 'token_firmante': 'b'},
            {'email': 'uno@example.com', 'token_firmante': 'c'},
        ]
        proceso = SimpleNamespace(indice_actual=1)

        indice = _indice_pendiente_actual(proceso, firmantes)
        indices_turno = _indices_firmas_en_turno(firmantes, indice)

        self.assertEqual(indices_turno, [0, 2])
        self.assertIn(_indice_por_token(firmantes, 'c'), indices_turno)

    def test_pending_index_recovers_when_saved_index_points_to_signed_row(self):
        firmantes = [
            {'email': 'uno@example.com', 'fecha_firma': '01/01/2026 10:00:00'},
            {'email': 'dos@example.com'},
        ]
        proceso = SimpleNamespace(indice_actual=1)

        self.assertEqual(_indice_pendiente_actual(proceso, firmantes), 1)


class SignatureAdjustmentHelpersTest(SimpleTestCase):
    def test_hash_can_be_used_when_signature_image_is_missing(self):
        firmantes = [{
            'nombre': 'Uno',
            'email': 'uno@example.com',
            'fecha_firma': '01/01/2026 10:00:00',
            'hash': 'a' * 64,
        }]

        with patch('motor_firmas.views._mongo_find_one', return_value=None):
            datos = _datos_ajuste_firmantes(firmantes)

        self.assertTrue(datos[0]['puede_reestampar'])
        self.assertEqual(datos[0]['tipo_reestampado'], 'hash')

    def test_hash_can_be_read_from_nested_metadata(self):
        firmante = {'metadata': {'document_hash': 'b' * 64}}

        self.assertEqual(_obtener_hash_para_reestampado(firmante), 'b' * 64)


class SignatureAdjustmentPdfTest(SimpleTestCase):
    def test_adjustment_appends_correction_page_without_redacting_original(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, 'ajuste.pdf')
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "CONTENIDO ORIGINAL", fontsize=12)
            doc.save(pdf_path)
            doc.close()

            result = utils.reubicar_firmas_en_pdf(
                pdf_path,
                [{
                    'key': 'firmante-1',
                    'nombre': 'UNO',
                    'email': 'uno@example.com',
                    'etiqueta': 'Usuario solicitante',
                    'fecha_firma': '25/06/2026 10:00',
                    'hash_firma': 'a' * 64,
                    'orden_anterior': 2,
                    'orden_nuevo': 1,
                }],
                actor_email='admin@example.com',
                actor_role='admin',
            )

            adjusted = fitz.open(pdf_path)
            self.assertEqual(len(adjusted), 2)
            self.assertIn("CONTENIDO ORIGINAL", adjusted[0].get_text("text"))
            self.assertIn("HOJA DE CORRE", adjusted[1].get_text("text"))
            self.assertIn('firmante-1', result['posiciones'])
            adjusted.close()


class HomeRedirectTest(SimpleTestCase):
    def setUp(self):
        self.client = Client()
        self.factory = RequestFactory()

    def _request_with_session(self, session_data=None):
        request = self.factory.get('/')
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        for key, value in (session_data or {}).items():
            request.session[key] = value
        return request

    def test_root_redirects_to_portal_login_without_session(self):
        response = home_redirect(self._request_with_session())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/portal/')

    def test_root_redirects_to_portal_dashboard_with_owner_session(self):
        response = home_redirect(self._request_with_session({'owner_email': 'usuario@example.com'}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/portal/dashboard/')

    def test_portal_login_has_admin_panel_link(self):
        response = self.client.get('/portal/')

        self.assertContains(response, 'Ir al panel administrativo')
        self.assertContains(response, '/admin-portal/')

    def test_portal_login_admin_link_points_to_dashboard_when_admin_session_exists(self):
        request = self._request_with_session({'admin_email': 'admin@example.com'})

        html = render_to_string('motor_firmas/portal_login.html', request=request)

        self.assertIn('/admin-portal/dashboard/', html)

    def test_portal_dashboard_shows_admin_switch_when_admin_session_exists(self):
        request = self._request_with_session({
            'owner_email': 'usuario@example.com',
            'admin_email': 'admin@example.com',
        })

        html = render_to_string(
            'motor_firmas/portal_dashboard.html',
            {'owner_email': 'usuario@example.com', 'documentos': [], 'permisos': []},
            request=request,
        )

        self.assertIn('Panel Admin', html)
        self.assertIn('/admin-portal/dashboard/', html)

    def test_admin_dashboard_shows_portal_switch_when_owner_session_exists(self):
        request = self._request_with_session({
            'owner_email': 'usuario@example.com',
            'admin_email': 'admin@example.com',
        })

        html = render_to_string(
            'motor_firmas/admin_dashboard.html',
            {
                'admin_email': 'admin@example.com',
                'docs_json': '[]',
                'saved_config': '{}',
                'carpetas_dominio': '[]',
                'plantillas': [],
                'es_superadmin': False,
            },
            request=request,
        )

        self.assertIn('Portal Usuario', html)
        self.assertIn('/portal/dashboard/', html)
