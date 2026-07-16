import base64
import json
import os
import tempfile
from datetime import datetime, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import patch

import fitz
import requests
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, override_settings

from . import utils
from .views import (
    _mongo_count,
    _mongo_delete_document,
    _mongo_find_one_by_id,
    _mongo_update_document,
    _firmx_curl_preview,
    _datos_ajuste_firmantes,
    firmx_registrar_documento,
    home_redirect,
    _indice_pendiente_actual,
    _indice_por_token,
    _indices_firmas_en_turno,
    _json_or_default,
    _documentos_firmados_usuario,
    _firmx_url_documento_visible,
    _normalizar_referencias_documento,
    _obtener_hash_para_reestampado,
    _proceso_pdf_puede_servirse,
    _relaciones_documento_firma,
    _url_firmada_expirada,
    procesar_firma,
    ver_pdf_proceso,
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

    @override_settings(FIRMX_API_BASE_URL='https://stage.firmx.mobilender.mx/digisign/api/v1')
    def test_firmx_curl_preview_redacts_base64_and_api_key(self):
        curl = _firmx_curl_preview('POST', '/documents/register/', {
            'document_name': 'Contrato',
            'document_base64': 'abc123',
        })

        self.assertIn('https://stage.firmx.mobilender.mx/digisign/api/v1/documents/register/', curl)
        self.assertIn('X-Api-Key: <FIRMX_API_KEY>', curl)
        self.assertIn('<base64_pdf_omitido:6 caracteres>', curl)
        self.assertNotIn('abc123', curl)

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


class DocumentReferenceHelpersTest(SimpleTestCase):
    def test_lists_all_completed_documents_for_owner(self):
        completed_without_pdf = SimpleNamespace(
            token_acceso='token-sin-pdf',
            reference_id='DOC-COMPLETADO-1',
            owner_email='owner@example.com',
            created_at=None,
            summary_data={},
        )
        completed_with_pdf = SimpleNamespace(
            token_acceso='token-con-pdf',
            reference_id='DOC-COMPLETADO-2',
            owner_email='owner@example.com',
            created_at=None,
            summary_data={'pdf_file_id': 'drive-file-id'},
        )

        with patch('motor_firmas.views._mongo_find', return_value=[completed_without_pdf, completed_with_pdf]) as find:
            documentos = _documentos_firmados_usuario('Owner@Example.com')

        find.assert_called_once()
        self.assertEqual(find.call_args.args[1], {'owner_email': 'owner@example.com', 'status': 'COMPLETED'})
        self.assertEqual([doc['reference_id'] for doc in documentos], ['DOC-COMPLETADO-1', 'DOC-COMPLETADO-2'])
        self.assertFalse(documentos[0]['pdf_available'])
        self.assertTrue(documentos[1]['pdf_available'])

    def test_firmx_completed_document_with_url_can_be_served(self):
        related = SimpleNamespace(
            pdf_path='',
            summary_data={'firmx_file_url': 'https://firmx.example.com/documento.pdf'},
        )

        self.assertTrue(_proceso_pdf_puede_servirse(related))

    def test_relation_map_resolves_related_pdf_from_token_not_stored_url(self):
        proceso = SimpleNamespace(
            reference_id='BASE-1',
            summary_data={
                'document_references': [{
                    'id': 'ref-1',
                    'related_token': 'token-fresco',
                    'related_pdf_url': 'https://firmx.example.com/expired.pdf?X-Amz-Expires=1',
                }]
            },
        )
        related = SimpleNamespace(token_acceso='token-fresco', reference_id='REL-1')

        with patch('motor_firmas.views._mongo_find_proceso_by_token', return_value=related):
            relaciones = _relaciones_documento_firma(proceso, '/documento-pdf/base/')

        self.assertEqual(relaciones['references'][0]['related_pdf_url'], '/documento-pdf/token-fresco/')
        self.assertEqual(relaciones['references'][0]['related_reference_id'], 'REL-1')
        self.assertEqual(relaciones['references'][0]['related_type_label'], 'Documento')

    def test_ver_pdf_proceso_serves_firmx_pdf_inline_from_api_url(self):
        request = RequestFactory().get('/documento-pdf/token-firmx/')
        initial = SimpleNamespace(
            token_acceso='token-firmx',
            summary_data={'firmx_id': 'firmx-1', 'firmx_file_url': 'https://firmx.example.com/expired.pdf'},
            pdf_path='',
            reference_id='REL-1',
        )
        refreshed = SimpleNamespace(
            token_acceso='token-firmx',
            summary_data={'firmx_id': 'firmx-1', 'firmx_file_url': 'https://firmx.example.com/fresh.pdf'},
            pdf_path='',
            reference_id='REL-1',
        )
        firmx_pdf = SimpleNamespace(
            status_code=200,
            content=b'%PDF-1.4 contenido',
            headers={'content-type': 'application/pdf'},
            text='%PDF-1.4 contenido',
        )

        with patch('motor_firmas.views._get_proceso_por_token_or_404', side_effect=[initial, refreshed]), \
                patch('motor_firmas.views._firmx_sync_status', return_value=(True, {})) as sync, \
                patch('motor_firmas.views.requests.get', return_value=firmx_pdf) as get:
            response = ver_pdf_proceso(request, 'token-firmx')

        sync.assert_called_once_with('firmx-1', force=True)
        get.assert_called_once_with('https://firmx.example.com/fresh.pdf', timeout=45, allow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response.content, b'%PDF-1.4 contenido')
        self.assertEqual(response['Cache-Control'], 'no-store, max-age=0')

    def test_ver_pdf_proceso_firmx_falls_back_to_local_pdf_when_api_url_is_not_pdf(self):
        request = RequestFactory().get('/documento-pdf/token-firmx/')
        html_response = SimpleNamespace(
            status_code=200,
            content=b'<html>no pdf</html>',
            headers={'content-type': 'text/html'},
            text='<html>no pdf</html>',
        )

        with tempfile.TemporaryDirectory() as tmpdir, override_settings(MEDIA_ROOT=tmpdir):
            local_path = os.path.join(tmpdir, 'FXP-LOCAL.pdf')
            with open(local_path, 'wb') as handle:
                handle.write(b'%PDF-1.4 local')

            initial = SimpleNamespace(
                token_acceso='token-firmx',
                summary_data={'firmx_id': 'firmx-1', 'firmx_file_url': 'https://firmx.example.com/html'},
                pdf_path=local_path,
                reference_id='FXP-LOCAL',
            )
            refreshed = SimpleNamespace(
                token_acceso='token-firmx',
                summary_data={'firmx_id': 'firmx-1', 'firmx_file_url': 'https://firmx.example.com/html'},
                pdf_path=local_path,
                reference_id='FXP-LOCAL',
            )

            with patch('motor_firmas.views._get_proceso_por_token_or_404', side_effect=[initial, refreshed]), \
                    patch('motor_firmas.views._firmx_sync_status', return_value=(True, {})), \
                    patch('motor_firmas.views._firmx_headers', return_value={'X-Api-Key': 'key'}), \
                    patch('motor_firmas.views.requests.get', return_value=html_response):
                response = ver_pdf_proceso(request, 'token-firmx')

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/pdf')
            self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 local')
            self.assertEqual(response['Cache-Control'], 'no-store, max-age=0')

    def test_ver_pdf_proceso_firmx_reports_http_401_error_details(self):
        request = RequestFactory().get('/documento-pdf/token-firmx/')
        proceso = SimpleNamespace(
            token_acceso='token-firmx',
            summary_data={
                'firmx_id': '1577',
                'firmx_base_url': 'https://stage.firmx.mobilender.mx/digisign/api/v1',
                'firmx_download_file_url': 'https://stage.firmx.mobilender.mx/digisign/api/v1/documents/download/document/1577/base64document_signed/token',
            },
            pdf_path='',
            reference_id='FXP-0000000014',
        )
        unauthorized = requests.Response()
        unauthorized.status_code = 401
        unauthorized._content = b'{"detail":"Authentication credentials were not provided."}'
        unauthorized.headers['content-type'] = 'application/json'

        with patch('motor_firmas.views._get_proceso_por_token_or_404', return_value=proceso), \
                patch('motor_firmas.views._firmx_sync_status', return_value=(False, 'FIRMX Error 401')), \
                patch('motor_firmas.views._firmx_headers', return_value={'X-Api-Key': 'key'}), \
                patch('motor_firmas.views.requests.get', return_value=unauthorized) as get:
            response = ver_pdf_proceso(request, 'token-firmx')

        self.assertEqual(get.call_count, 2)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response['Cache-Control'], 'no-store, max-age=0')
        body = response.content.decode('utf-8')
        self.assertIn('FXP-0000000014', body)
        self.assertIn('HTTP 401', body)
        self.assertIn('stage.firmx.mobilender.mx', body)
        self.assertIn('API Key guardada corresponda a ese endpoint FIRMX', body)

    def test_relation_map_marks_firmx_related_document(self):
        proceso = SimpleNamespace(
            reference_id='BASE-1',
            summary_data={'document_references': [{'id': 'ref-1', 'related_token': 'token-firmx'}]},
        )
        related = SimpleNamespace(
            token_acceso='token-firmx',
            reference_id='FXP-1',
            summary_data={
                'firmx_id': 'firmx-1',
                'firmx_file_url': 'https://firmx.example.com/visible.pdf?X-Amz-Signature=abc',
            },
        )

        with patch('motor_firmas.views._mongo_find_proceso_by_token', return_value=related), \
                patch('motor_firmas.views._firmx_sync_status', return_value=(False, 'sin red')):
            relaciones = _relaciones_documento_firma(proceso, '/documento-pdf/base/')

        self.assertEqual(relaciones['references'][0]['related_type'], 'firmx')
        self.assertEqual(relaciones['references'][0]['related_type_label'], 'FIRMX')
        self.assertEqual(
            relaciones['references'][0]['related_pdf_url'],
            'https://firmx.example.com/visible.pdf?X-Amz-Signature=abc',
        )

    def test_relation_map_uses_internal_route_for_expired_firmx_url(self):
        proceso = SimpleNamespace(
            reference_id='BASE-1',
            summary_data={'document_references': [{'id': 'ref-1', 'related_token': 'token-firmx'}]},
        )
        related = SimpleNamespace(
            token_acceso='token-firmx',
            reference_id='FXP-1',
            summary_data={
                'firmx_id': 'firmx-1',
                'firmx_file_url': 'https://firmx.example.com/doc.pdf?X-Amz-Date=20260630T162844Z&X-Amz-Expires=60',
            },
        )
        now = datetime(2026, 7, 15, 16, 30, tzinfo=datetime_timezone.utc)

        with patch('motor_firmas.views._mongo_find_proceso_by_token', return_value=related), \
                patch('motor_firmas.views._firmx_sync_status', return_value=(False, 'sin red')), \
                patch('motor_firmas.views.timezone.now', return_value=now):
            relaciones = _relaciones_documento_firma(proceso, '/documento-pdf/base/')

        self.assertEqual(relaciones['references'][0]['related_type'], 'firmx')
        self.assertEqual(relaciones['references'][0]['related_pdf_url'], '/documento-pdf/token-firmx/')

    def test_firmx_visible_url_skips_expired_signed_url(self):
        expired_url = 'https://firmx.example.com/doc.pdf?X-Amz-Date=20260630T162844Z&X-Amz-Expires=60'
        fresh_url = 'https://firmx.example.com/doc-fresh.pdf?X-Amz-Date=20260715T162844Z&X-Amz-Expires=3600'
        now = datetime(2026, 7, 15, 16, 30, tzinfo=datetime_timezone.utc)
        proceso = SimpleNamespace(
            summary_data={
                'firmx_file_url': expired_url,
                'firmx_download_file_url': fresh_url,
            },
            pdf_path='',
        )

        self.assertTrue(_url_firmada_expirada(expired_url, now=now))
        with patch('motor_firmas.views.timezone.now', return_value=now):
            self.assertEqual(_firmx_url_documento_visible(proceso), fresh_url)

    def test_normalizes_document_reference_for_completed_owner_document(self):
        related = SimpleNamespace(
            token_acceso='token-relacionado',
            reference_id='DOC-FIRMADO-1',
            owner_email='owner@example.com',
            status='COMPLETED',
            summary_data={'pdf_file_id': 'drive-file-id'},
        )
        raw_refs = [{
            'id': 'ref-1',
            'page': '2',
            'x': '0.2',
            'y': '0.3',
            'width': '0.4',
            'height': '0.2',
            'snippet_image': 'data:image/png;base64,AAAA',
            'related_token': 'token-relacionado',
        }]

        with patch('motor_firmas.views._mongo_find_proceso_by_token', return_value=related):
            refs = _normalizar_referencias_documento(raw_refs, 'owner@example.com')

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['related_reference_id'], 'DOC-FIRMADO-1')
        self.assertEqual(refs[0]['page'], 2)
        self.assertEqual(refs[0]['snippet_image'], 'data:image/png;base64,AAAA')

    def test_rejects_document_reference_from_another_owner(self):
        related = SimpleNamespace(
            token_acceso='token-relacionado',
            reference_id='DOC-FIRMADO-1',
            owner_email='otro@example.com',
            status='COMPLETED',
            summary_data={'pdf_file_id': 'drive-file-id'},
        )

        with patch('motor_firmas.views._mongo_find_proceso_by_token', return_value=related):
            with self.assertRaises(ValueError):
                _normalizar_referencias_documento([{'related_token': 'token-relacionado'}], 'owner@example.com')


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


class FirmaUiTemplateTest(SimpleTestCase):
    def _render_signature_ui(self, is_registered):
        return render_to_string('motor_firmas/firma_ui.html', {
            'token': 'token-prueba',
            'firmante_token': 'firmante-prueba',
            'nombre_firmante': 'Firmante',
            'email_firmante': 'firmante@example.com',
            'view_info': 'file',
            'summary_data': {},
            'pdf_url': '',
            'pdf_available': False,
            'is_registered': is_registered,
            'campos_a_llenar': [],
            'is_message_view': False,
            'cant_firmas': 1,
        })

    def _opening_tag_after_id(self, html, element_id):
        return html.split(f'id="{element_id}"', 1)[1].split('>', 1)[0]

    def test_pin_signature_button_stays_enabled_when_preview_is_unavailable(self):
        html = self._render_signature_ui(is_registered=True)

        self.assertIn('No se pudo cargar la vista previa del PDF', html)
        self.assertNotIn('disabled', self._opening_tag_after_id(html, 'btnFirmarPin'))

    def test_canvas_signature_button_stays_enabled_when_preview_is_unavailable(self):
        html = self._render_signature_ui(is_registered=False)

        self.assertIn('No se pudo cargar la vista previa del PDF', html)
        self.assertNotIn('disabled', self._opening_tag_after_id(html, 'btnFirmarCanvas'))


class ProcesarFirmaPdfRecoveryTest(SimpleTestCase):
    class N8NResponse:
        status_code = 200
        headers = {}
        text = ''

        def json(self):
            return {}

    def test_missing_local_pdf_is_rehydrated_before_signing(self):
        factory = RequestFactory()
        request = factory.post(
            '/api/procesar/token-prueba/firmante-prueba/',
            data=json.dumps({'firma_base64': 'data:image/png;base64,ZmlybWE=', 'variables': {}}),
            content_type='application/json',
        )
        proceso = SimpleNamespace(
            _id='proceso-1',
            reference_id='DOC-1',
            token_acceso='token-prueba',
            pdf_path='',
            firmantes=[{
                'nombre': 'Firmante',
                'email': 'firmante@example.com',
                'token_firmante': 'firmante-prueba',
            }],
            indice_actual=1,
            status='PROCESSING',
            summary_data={},
            valores_capturados={},
            owner_email='',
            dir_drive='',
            exec_mode='normal',
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            proceso.pdf_path = os.path.join(tmpdir, 'no-existe-doc-1.pdf')
            recovered_pdf = os.path.join(tmpdir, 'DOC-1.pdf')

            def rehydrate(proceso_arg):
                with open(recovered_pdf, 'wb') as f:
                    f.write(b'%PDF-1.4\n%%EOF\n')
                proceso_arg.pdf_path = recovered_pdf

            def copy_evidence(firmante, *_args, **_kwargs):
                firmante['fecha_firma'] = '14/07/2026 12:00:00'

            with self.settings(MEDIA_ROOT=tmpdir):
                with patch('motor_firmas.views._get_proceso_por_token_or_404', return_value=proceso), \
                        patch('motor_firmas.views._asegurar_proceso_pdf_local', side_effect=rehydrate) as ensure_pdf, \
                        patch('motor_firmas.views.estampar_firma_en_pdf', return_value={'hash': 'a' * 64}) as stamp, \
                        patch('motor_firmas.views._copiar_evidencia_firma', side_effect=copy_evidence), \
                        patch('motor_firmas.views._marcar_notificaciones_firma'), \
                        patch('motor_firmas.views._actualizar_proceso_firma_mongo'), \
                        patch('motor_firmas.views._n8n_storage_data_for_proceso', return_value={}), \
                        patch('motor_firmas.views.tracked_post', return_value=self.N8NResponse()):
                    response = procesar_firma(request, 'token-prueba', 'firmante-prueba')

        self.assertEqual(response.status_code, 200, response.content)
        ensure_pdf.assert_called_once_with(proceso)
        stamp.assert_called_once()
        self.assertEqual(stamp.call_args.args[0], recovered_pdf)

    def test_existing_absolute_pdf_can_be_signed_when_preview_is_unavailable(self):
        factory = RequestFactory()
        request = factory.post(
            '/api/procesar/token-prueba/firmante-prueba/',
            data=json.dumps({'firma_base64': 'data:image/png;base64,ZmlybWE=', 'variables': {}}),
            content_type='application/json',
        )

        def copy_evidence(firmante, *_args, **_kwargs):
            firmante['fecha_firma'] = '14/07/2026 12:00:00'

        with tempfile.TemporaryDirectory() as storage_dir, tempfile.TemporaryDirectory() as media_root:
            pdf_path = os.path.join(storage_dir, 'DOC-2.pdf')
            with open(pdf_path, 'wb') as f:
                f.write(b'%PDF-1.4\n%%EOF\n')

            proceso = SimpleNamespace(
                _id='proceso-2',
                reference_id='DOC-2',
                token_acceso='token-prueba',
                pdf_path=pdf_path,
                firmantes=[{
                    'nombre': 'Firmante',
                    'email': 'firmante@example.com',
                    'token_firmante': 'firmante-prueba',
                }],
                indice_actual=1,
                status='PROCESSING',
                summary_data={},
                valores_capturados={},
                owner_email='',
                dir_drive='',
                exec_mode='normal',
            )

            with self.settings(MEDIA_ROOT=media_root):
                with patch('motor_firmas.views._get_proceso_por_token_or_404', return_value=proceso), \
                        patch('motor_firmas.views._asegurar_proceso_pdf_local') as ensure_pdf, \
                        patch('motor_firmas.views.estampar_firma_en_pdf', return_value={'hash': 'b' * 64}) as stamp, \
                        patch('motor_firmas.views._copiar_evidencia_firma', side_effect=copy_evidence), \
                        patch('motor_firmas.views._marcar_notificaciones_firma'), \
                        patch('motor_firmas.views._actualizar_proceso_firma_mongo'), \
                        patch('motor_firmas.views._n8n_storage_data_for_proceso', return_value={}), \
                        patch('motor_firmas.views.tracked_post', return_value=self.N8NResponse()):
                    response = procesar_firma(request, 'token-prueba', 'firmante-prueba')

        self.assertEqual(response.status_code, 200, response.content)
        ensure_pdf.assert_not_called()
        stamp.assert_called_once()
        self.assertEqual(stamp.call_args.args[0], pdf_path)


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

    def test_portal_dashboard_has_view_mode_toggle(self):
        request = self._request_with_session({'owner_email': 'usuario@example.com'})

        html = render_to_string(
            'motor_firmas/portal_dashboard.html',
            {'owner_email': 'usuario@example.com', 'documentos': [], 'permisos': []},
            request=request,
        )

        self.assertIn('btnViewCards', html)
        self.assertIn('btnViewList', html)
        self.assertIn('Lista', html)

    def test_portal_firmx_admin_template_shows_api_panel(self):
        request = self._request_with_session({
            'owner_email': 'usuario@example.com',
            'admin_email': 'admin@example.com',
        })

        html = render_to_string(
            'motor_firmas/portal_firmx.html',
            {
                'owner_email': 'usuario@example.com',
                'firmx_base_url': 'https://stage.firmx.mobilender.mx/digisign/api/v1',
                'es_admin_firmx': True,
            },
            request=request,
        )

        self.assertIn('Step 1 de 4', html)
        self.assertIn('PDF y firmantes', html)
        self.assertIn('firmxToggleIntegrationSideButton', html)
        self.assertIn('firmxToggleSignersButton', html)
        self.assertIn('firmxZoomLabel', html)
        self.assertIn('API FIRMX', html)
        self.assertIn('firmxCurlPreview', html)

    @override_settings(FIRMX_API_BASE_URL='https://stage.firmx.mobilender.mx/digisign/api/v1')
    def test_firmx_register_admin_response_includes_sanitized_curl(self):
        request = self.factory.post('/api/firmx/register-document/', data={
            'pdf_file': SimpleUploadedFile('contrato.pdf', b'%PDF-1.4 contenido', content_type='application/pdf'),
            'document_name': 'Contrato',
            'dead_line_to_sign': '2026-07-01',
            'signers_json': json.dumps([{'name': 'Juan Perez', 'email': 'juan@example.com'}]),
            'viewers_json': '[]',
            'tags_json': '[]',
        })
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session['owner_email'] = 'usuario@example.com'
        request.session['admin_email'] = 'admin@example.com'

        fake_response = SimpleNamespace(
            status_code=200,
            headers={'content-type': 'application/json'},
            json=lambda: {'document_id': 'firmx-123'},
            text='{"document_id":"firmx-123"}',
        )

        with patch('motor_firmas.views._usuario_tiene_permiso', return_value=True), \
                patch('motor_firmas.views.requests.post', return_value=fake_response):
            response = firmx_registrar_documento(request)

        payload = json.loads(response.content)
        self.assertEqual(payload['status'], 'success')
        self.assertIn('firmx_curl', payload)
        self.assertIn('<base64_pdf_omitido:', payload['firmx_curl'])
        self.assertNotIn(base64.b64encode(b'%PDF-1.4 contenido').decode('ascii'), payload['firmx_curl'])

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
