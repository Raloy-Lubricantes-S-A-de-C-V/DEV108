import base64
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import patch

import fitz
import requests
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone

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
    _firmx_api_key,
    _firmx_configuracion_urls,
    _firmx_url_documento_visible,
    _campos_llenado_libre,
    _normalizar_campos_llenado,
    _document_variables_desde_campos_llenado,
    _deduplicar_pdfs_usuario_visibles,
    _ejecutar_subida_pdf_usuario_n8n,
    _normalizar_referencias_documento,
    _obtener_hash_para_reestampado,
    _programar_resguardo_pdf_usuario_pendiente,
    _proceso_pdf_puede_servirse,
    _relaciones_documento_firma,
    _url_firmada_expirada,
    admin_api,
    estado_firma,
    iniciar_firma_libre,
    n8n_monitor_events,
    procesar_firma,
    subir_pdf_usuario,
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
            if isinstance(value, dict) and '$ne' in value:
                if document.get(key) == value['$ne']:
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


class AdminActionGuardTemplateTest(SimpleTestCase):
    def _template(self, filename):
        path = os.path.join(
            os.path.dirname(__file__),
            'templates',
            'motor_firmas',
            filename,
        )
        with open(path, encoding='utf-8') as template:
            return template.read()

    def test_base_includes_admin_page_loader_and_fetch_guard(self):
        template = self._template('base.html')

        self.assertIn('id="adminActionOverlay"', template)
        self.assertIn('window.fetch = function', template)
        self.assertIn("url.pathname === '/api/admin-action/listar_docs_dashboard/'", template)
        self.assertIn("document.addEventListener('submit'", template)
        self.assertIn("confirmAction('¿Confirmas ejecutar esta acción?')", template)
        self.assertIn('window.AdminActionGuard', template)

    def test_admin_write_actions_request_confirmation(self):
        expectations = {
            'admin_administradores.html': [
                '¿Confirmas añadir como administrador',
                '¿Confirmas ${accion} a este administrador?',
            ],
            'admin_login.html': [
                '¿Confirmas ingresar al panel administrativo',
                '¿Confirmas solicitar un PIN temporal por correo',
            ],
            'admin_dashboard.html': [
                '¿Confirmas guardar la configuración global de Drive?',
                '¿Confirmas guardar la carpeta y marca del dominio',
                '¿Confirmas guardar esta configuración de vista del administrador?',
                '¿Confirmas enviar la invitación de registro?',
            ],
            'admin_crear_plantilla.html': [
                '¿Confirmas analizar este documento con IA?',
                '¿Confirmas finalizar y guardar esta plantilla?',
            ],
            'admin_editar_plantilla.html': [
                '¿Confirmas guardar los cambios de esta plantilla?',
            ],
            'admin_usuarios_detalle.html': [
                '¿Confirmas guardar la configuración de este usuario?',
            ],
            'ajustar_firmas.html': [
                '¿Confirmas guardar esta hoja de corrección y reestampar el documento?',
            ],
        }

        for filename, snippets in expectations.items():
            template = self._template(filename)
            for snippet in snippets:
                self.assertIn(snippet, template)


class DocumentReferenceHelpersTest(SimpleTestCase):
    def test_normalizes_fill_fields_for_existing_signer(self):
        firmantes = [{
            'nombre': 'Firmante Uno',
            'email': 'Firmante@Example.com',
        }]
        raw_fields = [{
            'id': 'field-1',
            'key': 'Campo Libre 1',
            'label': 'Número de orden',
            'signer_email': 'firmante@example.com',
            'page': '2',
            'x': '0.25',
            'y': '0.30',
            'width': '0.40',
            'height': '0.05',
        }]

        fields = _normalizar_campos_llenado(raw_fields, firmantes)

        self.assertEqual(fields[0]['key'], 'campo_libre_1')
        self.assertEqual(fields[0]['signer_email'], 'firmante@example.com')
        self.assertEqual(fields[0]['signer_name'], 'FIRMANTE UNO')
        self.assertEqual(fields[0]['page'], 2)
        self.assertEqual(_document_variables_desde_campos_llenado(fields), {
            'campo_libre_1': 'firmante@example.com',
        })

    def test_fill_fields_reject_unknown_signer(self):
        with self.assertRaisesMessage(ValueError, 'firmante existente'):
            _normalizar_campos_llenado(
                [{'label': 'Dato', 'signer_email': 'otro@example.com'}],
                [{'nombre': 'Uno', 'email': 'uno@example.com'}],
            )

    def test_fill_fields_for_signer_skip_captured_values(self):
        summary_data = {
            'fill_fields': [
                {'key': 'dato_1', 'label': 'Dato 1', 'signer_email': 'uno@example.com'},
                {'key': 'dato_2', 'label': 'Dato 2', 'signer_email': 'dos@example.com'},
            ]
        }

        fields = _campos_llenado_libre(summary_data, 'UNO@example.com', {'dato_1': 'OK'})

        self.assertEqual(fields, [])

    @override_settings(
        FIRMX_API_BASE_URL='https://firmx.mx/digisign/api/v1',
        FIRMX_API_KEY='settings-key',
    )
    def test_firmx_api_key_can_be_selected_by_endpoint(self):
        config = SimpleNamespace(
            api_key='global-prod-key',
            firmx_base_url='https://firmx.mx/digisign/api/v1',
            base_urls=[
                {
                    'url': 'https://stage.firmx.mobilender.mx/digisign/api/v1',
                    'api_key': 'stage-key',
                    'created_at': '',
                    'updated_at': '',
                },
                {
                    'url': 'https://firmx.mx/digisign/api/v1',
                    'created_at': '',
                    'updated_at': '',
                },
            ],
        )

        with patch('motor_firmas.views._mongo_find_one', return_value=config):
            self.assertEqual(
                _firmx_api_key('https://stage.firmx.mobilender.mx/digisign/api/v1'),
                'stage-key',
            )
            self.assertEqual(
                _firmx_api_key('https://firmx.mx/digisign/api/v1'),
                'global-prod-key',
            )
            public_config = _firmx_configuracion_urls()
            private_config = _firmx_configuracion_urls(include_secrets=True)

        stage_public = public_config['base_urls'][0]
        stage_private = private_config['base_urls'][0]
        self.assertTrue(stage_public['has_api_key'])
        self.assertNotIn('api_key', stage_public)
        self.assertEqual(stage_private['api_key'], 'stage-key')

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
            'exec_mode': 'libre',
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

    def test_signature_submit_waits_for_status_confirmation(self):
        html = self._render_signature_ui(is_registered=True)

        self.assertIn("let statusUrl = '/api/firma-estado/token-prueba/';", html)
        self.assertIn("statusUrl += 'firmante-prueba/';", html)
        self.assertIn('confirmarFirmaAplicada', html)
        self.assertIn('No se pudo confirmar la firma', html)


class EstadoFirmaApiTest(SimpleTestCase):
    def test_estado_firma_confirma_firmante_con_fecha_firma(self):
        factory = RequestFactory()
        request = factory.get('/api/firma-estado/token-prueba/firmante-prueba/')
        proceso = SimpleNamespace(
            status='PROCESSING',
            firmantes=[{
                'nombre': 'Firmante',
                'email': 'firmante@example.com',
                'token_firmante': 'firmante-prueba',
                'fecha_firma': '24/07/2026 10:00:00',
            }],
        )

        with patch('motor_firmas.views._get_proceso_por_token_or_404', return_value=proceso):
            response = estado_firma(request, 'token-prueba', 'firmante-prueba')

        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertEqual(payload['status'], 'success')
        self.assertTrue(payload['signed'])
        self.assertEqual(payload['fecha_firma'], '24/07/2026 10:00:00')

    def test_estado_firma_reporta_pending_sin_fecha_firma(self):
        factory = RequestFactory()
        request = factory.get('/api/firma-estado/token-prueba/firmante-prueba/')
        proceso = SimpleNamespace(
            status='PROCESSING',
            firmantes=[{
                'nombre': 'Firmante',
                'email': 'firmante@example.com',
                'token_firmante': 'firmante-prueba',
            }],
        )

        with patch('motor_firmas.views._get_proceso_por_token_or_404', return_value=proceso):
            response = estado_firma(request, 'token-prueba', 'firmante-prueba')

        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertEqual(payload['status'], 'pending')
        self.assertFalse(payload['signed'])


class ProcesarFirmaPdfRecoveryTest(SimpleTestCase):
    class N8NResponse:
        status_code = 200
        headers = {}
        text = ''

        def json(self):
            return {}

    class N8NUnusedRespondResponse:
        status_code = 500
        headers = {'content-type': 'application/json'}
        text = '{"code":0,"message":"Unused Respond to Webhook node found in the workflow"}'

        def json(self):
            return {"code": 0, "message": "Unused Respond to Webhook node found in the workflow"}

    class N8NBlockingErrorResponse:
        status_code = 500
        headers = {'content-type': 'application/json'}
        text = '{"code":0,"message":"NodeApiError: Drive permission denied"}'

        def json(self):
            return {"code": 0, "message": "NodeApiError: Drive permission denied"}

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

    def test_free_fill_field_is_required_for_assigned_signer(self):
        factory = RequestFactory()
        request = factory.post(
            '/api/procesar/token-prueba/firmante-prueba/',
            data=json.dumps({'firma_base64': 'data:image/png;base64,ZmlybWE=', 'variables': {}}),
            content_type='application/json',
        )
        proceso = SimpleNamespace(
            _id='proceso-fill',
            reference_id='DOC-FILL',
            token_acceso='token-prueba',
            pdf_path='/tmp/no-necesario.pdf',
            firmantes=[{
                'nombre': 'Firmante',
                'email': 'firmante@example.com',
                'token_firmante': 'firmante-prueba',
            }],
            indice_actual=1,
            status='PROCESSING',
            summary_data={
                'fill_fields': [{
                    'key': 'numero_cliente',
                    'label': 'Número de cliente',
                    'signer_email': 'firmante@example.com',
                    'page': 1,
                    'x': 0.1,
                    'y': 0.2,
                    'width': 0.3,
                    'height': 0.04,
                }]
            },
            valores_capturados={},
            owner_email='',
            dir_drive='',
            exec_mode='libre',
        )

        with patch('motor_firmas.views._get_proceso_por_token_or_404', return_value=proceso):
            response = procesar_firma(request, 'token-prueba', 'firmante-prueba')

        self.assertEqual(response.status_code, 400, response.content)
        payload = json.loads(response.content)
        self.assertIn('Número de cliente', payload['missing_fields'])

    def test_repeated_post_for_already_signed_token_returns_success(self):
        factory = RequestFactory()
        request = factory.post(
            '/api/procesar/token-prueba/firmante-prueba/',
            data=json.dumps({'firma_base64': 'data:image/png;base64,ZmlybWE=', 'variables': {}}),
            content_type='application/json',
        )
        proceso = SimpleNamespace(
            _id='proceso-retry',
            reference_id='DOC-RETRY',
            token_acceso='token-prueba',
            pdf_path='/tmp/no-necesario.pdf',
            firmantes=[
                {
                    'nombre': 'Firmante',
                    'email': 'firmante@example.com',
                    'token_firmante': 'firmante-prueba',
                    'fecha_firma': '24/07/2026 10:00:00',
                },
                {
                    'nombre': 'Siguiente',
                    'email': 'siguiente@example.com',
                    'token_firmante': 'siguiente-prueba',
                },
            ],
            indice_actual=2,
            status='PROCESSING',
            summary_data={},
            valores_capturados={},
            owner_email='',
            dir_drive='',
            exec_mode='normal',
        )

        with patch('motor_firmas.views._get_proceso_por_token_or_404', return_value=proceso), \
                patch('motor_firmas.views.estampar_firma_en_pdf') as stamp:
            response = procesar_firma(request, 'token-prueba', 'firmante-prueba')

        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertEqual(payload['status'], 'success')
        self.assertTrue(payload['already_signed'])
        stamp.assert_not_called()

    def test_unused_respond_webhook_error_does_not_block_completed_signature(self):
        factory = RequestFactory()
        request = factory.post(
            '/api/procesar/token-prueba/firmante-prueba/',
            data=json.dumps({'firma_base64': 'data:image/png;base64,ZmlybWE=', 'variables': {}}),
            content_type='application/json',
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, 'DOC-N8N.pdf')
            with open(pdf_path, 'wb') as f:
                f.write(b'%PDF-1.4\n%%EOF\n')

            def copy_evidence(firmante, *_args, **_kwargs):
                firmante['fecha_firma'] = '16/07/2026 17:08:08'

            proceso = SimpleNamespace(
                _id='proceso-n8n',
                reference_id='DOC-N8N',
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

            with patch('motor_firmas.views._get_proceso_por_token_or_404', return_value=proceso), \
                    patch('motor_firmas.views.estampar_firma_en_pdf', return_value={'hash': 'c' * 64}), \
                    patch('motor_firmas.views._copiar_evidencia_firma', side_effect=copy_evidence), \
                    patch('motor_firmas.views._marcar_notificaciones_firma'), \
                    patch('motor_firmas.views._actualizar_proceso_firma_mongo'), \
                    patch('motor_firmas.views._n8n_storage_data_for_proceso', return_value={}), \
                    patch('motor_firmas.views.tracked_post', return_value=self.N8NUnusedRespondResponse()), \
                    patch('motor_firmas.views._registrar_pdf_final_drive_id') as register_drive, \
                    patch('motor_firmas.views._registrar_advertencia_finalizacion_n8n',
                          return_value={'type': 'unused_respond_to_webhook'}) as register_warning:
                response = procesar_firma(request, 'token-prueba', 'firmante-prueba')

        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['n8n_warning']['type'], 'unused_respond_to_webhook')
        register_warning.assert_called_once()
        register_drive.assert_not_called()

    def test_firma_libre_finalization_errors_do_not_block_completed_signature_response(self):
        factory = RequestFactory()
        request = factory.post(
            '/api/procesar/token-prueba/firmante-prueba/',
            data=json.dumps({'firma_base64': 'data:image/png;base64,ZmlybWE=', 'variables': {}}),
            content_type='application/json',
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, 'LIBRE-N8N-BLOCK.pdf')
            with open(pdf_path, 'wb') as f:
                f.write(b'%PDF-1.4\n%%EOF\n')

            def copy_evidence(firmante, *_args, **_kwargs):
                firmante['fecha_firma'] = '16/07/2026 17:08:08'

            proceso = SimpleNamespace(
                _id='proceso-n8n-block',
                reference_id='LIBRE-N8N-BLOCK',
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
                exec_mode='libre',
            )

            with patch('motor_firmas.views._get_proceso_por_token_or_404', return_value=proceso), \
                    patch('motor_firmas.views.estampar_firma_en_pdf', return_value={'hash': 'd' * 64}), \
                    patch('motor_firmas.views._copiar_evidencia_firma', side_effect=copy_evidence), \
                    patch('motor_firmas.views._marcar_notificaciones_firma'), \
                    patch('motor_firmas.views._actualizar_proceso_firma_mongo'), \
                    patch('motor_firmas.views._n8n_storage_data_for_proceso', return_value={}), \
                    patch('motor_firmas.views.tracked_post', return_value=self.N8NBlockingErrorResponse()), \
                    patch('motor_firmas.views._registrar_advertencia_finalizacion_n8n',
                          return_value={'type': 'finalization_webhook_error'}) as register_warning:
                response = procesar_firma(request, 'token-prueba', 'firmante-prueba')

        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['n8n_warning']['type'], 'finalization_webhook_error')
        register_warning.assert_called_once()


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


class SubirPdfUsuarioTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _post_pdf_request(self, filename='SCANNER@RALOY.COM.MX_20260724_113548.PDF'):
        request = self.factory.post('/api/subir-pdf-usuario/', {
            'pdf_file': SimpleUploadedFile(filename, b'%PDF-1.4\n%test\n', content_type='application/pdf'),
        })
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session['owner_email'] = 'alopez@consorcionova.com'
        return request

    def _n8n_response(self, payload, status_code=200):
        return SimpleNamespace(
            status_code=status_code,
            headers={'content-type': 'application/json'},
            json=lambda: payload,
            text=json.dumps(payload),
        )

    def _find_one_folder_only(self, model, query=None):
        if getattr(model, '__name__', '') == 'CarpetaDominio':
            return SimpleNamespace(drive_folder_id='drive-folder-raloy')
        return None

    def test_subida_pdf_usuario_acepta_pdf_y_programa_n8n_en_background(self):
        request = self._post_pdf_request()
        collection = FakeMongoCollection([])

        with tempfile.TemporaryDirectory() as media_root, \
                override_settings(MEDIA_ROOT=media_root), \
                patch('motor_firmas.views._mongo_find_one', side_effect=self._find_one_folder_only), \
                patch('motor_firmas.views._mongo_collection', return_value=collection), \
                patch('motor_firmas.views._programar_subida_pdf_usuario_n8n') as background_upload, \
                patch('motor_firmas.views.tracked_post') as tracked:
            response = subir_pdf_usuario(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['nombre'], 'SCANNER@RALOY.COM.MX_20260724_113548.PDF')
        self.assertTrue(payload['drive_pending'])
        self.assertEqual(len(collection.documents), 1)
        self.assertEqual(collection.documents[0]['owner_email'], 'alopez@consorcionova.com')
        self.assertEqual(collection.documents[0]['drive_file_id'], '')
        self.assertEqual(collection.documents[0]['upload_status'], 'pending_n8n')
        self.assertTrue(collection.documents[0]['archivo_local'].startswith('pdfs_libres/'))
        background_upload.assert_called_once()
        self.assertEqual(background_upload.call_args.args[5], 'drive-folder-raloy')
        tracked.assert_not_called()

    def test_worker_subida_pdf_usuario_deja_pendiente_y_notifica_monitor_si_n8n_responde_502(self):
        collection = FakeMongoCollection([{
            '_id': 'doc-1',
            'id_documento': 'pdf-123',
            'nombre': 'contrato.pdf',
            'owner_email': 'alopez@consorcionova.com',
            'drive_file_id': '',
            'upload_status': 'pending_n8n',
            'archivo_local': 'pdfs_libres/contrato.pdf',
            'upload_sha256': 'abc',
        }])
        doc = SimpleNamespace(**collection.documents[0])
        response_502 = SimpleNamespace(
            status_code=502,
            headers={'content-type': 'text/html'},
            text='<html><h1>502 Bad Gateway</h1></html>',
            json=lambda: {},
        )

        with patch('motor_firmas.views.requests.post', return_value=response_502), \
                patch('motor_firmas.views._mongo_collection', return_value=collection), \
                patch('motor_firmas.views._registrar_evento_global_n8n_monitor') as monitor:
            ok = _ejecutar_subida_pdf_usuario_n8n(
                doc,
                'alopez@consorcionova.com',
                'contrato.pdf',
                b'%PDF-1.4\n%test\n',
                'abc',
                'drive-folder-raloy',
            )

        self.assertFalse(ok)
        self.assertEqual(collection.documents[0]['upload_status'], 'pending_n8n')
        self.assertIn('502 Bad Gateway', collection.documents[0]['n8n_upload_error'])
        monitor.assert_called_once()
        event = monitor.call_args.args[0]
        self.assertFalse(event['ok'])
        self.assertEqual(event['http_status'], 502)
        self.assertEqual(event['decision_label'], 'FALLA - PARAR')

    def test_worker_subida_pdf_usuario_actualiza_drive_file_id_si_n8n_confirma(self):
        collection = FakeMongoCollection([{
            '_id': 'doc-1',
            'id_documento': 'pdf-123',
            'nombre': 'contrato.pdf',
            'owner_email': 'alopez@consorcionova.com',
            'drive_file_id': '',
            'upload_status': 'pending_n8n',
            'archivo_local': '',
            'upload_sha256': 'abc',
        }])
        doc = SimpleNamespace(**collection.documents[0])

        with tempfile.TemporaryDirectory() as media_root, \
                override_settings(MEDIA_ROOT=media_root), \
                patch('motor_firmas.views.requests.post',
                      return_value=self._n8n_response({'status': 'success', 'file_id': 'drive-file-123'})), \
                patch('motor_firmas.views._mongo_collection', return_value=collection), \
                patch('motor_firmas.views._registrar_evento_global_n8n_monitor') as monitor:
            ok = _ejecutar_subida_pdf_usuario_n8n(
                doc,
                'alopez@consorcionova.com',
                'contrato.pdf',
                b'%PDF-1.4\n%test\n',
                'abc',
                'drive-folder-raloy',
            )

        self.assertTrue(ok)
        self.assertEqual(collection.documents[0]['upload_status'], 'uploaded')
        self.assertEqual(collection.documents[0]['drive_file_id'], 'drive-file-123')
        self.assertTrue(collection.documents[0]['archivo_local'].startswith('pdfs_libres/'))
        event = monitor.call_args.args[0]
        self.assertTrue(event['ok'])
        self.assertEqual(event['http_status'], 200)

    def test_subida_pdf_usuario_reusa_borrador_si_el_mismo_pdf_ya_tiene_drive_id(self):
        request = self._post_pdf_request()
        upload_sha256 = hashlib.sha256(b'%PDF-1.4\n%test\n').hexdigest()
        collection = FakeMongoCollection([{
            '_id': 'doc-1',
            'id_documento': 'pdf-existente',
            'nombre': 'SCANNER@RALOY.COM.MX_20260724_113548.PDF',
            'owner_email': 'alopez@consorcionova.com',
            'drive_file_id': 'drive-file-existente',
            'upload_sha256': upload_sha256,
            'upload_status': 'uploaded',
        }])

        with patch('motor_firmas.views._mongo_collection', return_value=collection), \
                patch('motor_firmas.views._programar_subida_pdf_usuario_n8n') as background_upload, \
                patch('motor_firmas.views.tracked_post') as tracked:
            response = subir_pdf_usuario(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['id'], 'pdf-existente')
        self.assertTrue(payload['deduplicated'])
        background_upload.assert_not_called()
        tracked.assert_not_called()

    def test_subida_pdf_usuario_reintento_inmediato_reusa_pendiente_sin_duplicar_n8n(self):
        collection = FakeMongoCollection([])

        def find_one(model, query=None):
            if getattr(model, '__name__', '') == 'CarpetaDominio':
                return SimpleNamespace(drive_folder_id='drive-folder-raloy')
            document = collection.find_one(query or {})
            return SimpleNamespace(**document) if document else None

        with tempfile.TemporaryDirectory() as media_root, \
                override_settings(MEDIA_ROOT=media_root), \
                patch('motor_firmas.views._mongo_find_one', side_effect=find_one), \
                patch('motor_firmas.views._mongo_collection', return_value=collection), \
                patch('motor_firmas.views._programar_subida_pdf_usuario_n8n') as background_upload, \
                patch('motor_firmas.views.tracked_post') as tracked:
            first_response = subir_pdf_usuario(self._post_pdf_request())
            second_response = subir_pdf_usuario(self._post_pdf_request())

        first_payload = json.loads(first_response.content)
        second_payload = json.loads(second_response.content)
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_payload['status'], 'success')
        self.assertEqual(second_payload['status'], 'success')
        self.assertEqual(first_payload['id'], second_payload['id'])
        self.assertFalse(first_payload['deduplicated'])
        self.assertTrue(second_payload['deduplicated'])
        self.assertEqual(len(collection.documents), 1)
        self.assertEqual(collection.documents[0]['upload_status'], 'pending_n8n')
        background_upload.assert_called_once()
        tracked.assert_not_called()

    def test_reintento_pendiente_programa_n8n_si_existe_archivo_local_y_paso_cooldown(self):
        with tempfile.TemporaryDirectory() as media_root:
            rel_path = os.path.join('pdfs_libres', 'contrato.pdf')
            abs_dir = os.path.join(media_root, 'pdfs_libres')
            os.makedirs(abs_dir, exist_ok=True)
            with open(os.path.join(media_root, rel_path), 'wb') as f:
                f.write(b'%PDF-1.4\n%retry\n')

            doc = SimpleNamespace(
                id_documento='pdf-123',
                nombre='contrato.pdf',
                drive_file_id='',
                upload_status='pending_n8n',
                archivo_local=rel_path,
                upload_sha256='',
                last_n8n_upload_attempt_at=timezone.now().replace(tzinfo=None) - timedelta(minutes=5),
            )

            with override_settings(MEDIA_ROOT=media_root), \
                    patch('motor_firmas.views._drive_folder_id_para_owner_pdf_usuario',
                          return_value=('drive-folder-raloy', 'consorcionova.com')), \
                    patch('motor_firmas.views._mongo_update_document'), \
                    patch('motor_firmas.views._programar_subida_pdf_usuario_n8n') as background_upload:
                result = _programar_resguardo_pdf_usuario_pendiente(doc, 'alopez@consorcionova.com')

        self.assertIs(result, background_upload.return_value)
        background_upload.assert_called_once()
        self.assertEqual(background_upload.call_args.args[2], 'contrato.pdf')
        self.assertEqual(background_upload.call_args.args[5], 'drive-folder-raloy')


class AdminInviteRegistroTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _post_request(self, email='alopez@consorcionova.com'):
        request = self.factory.post(
            '/api/admin-action/invitar_registro/',
            data=json.dumps({'email': email}),
            content_type='application/json',
        )
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session['admin_email'] = 'admin@example.com'
        return request

    def _admin(self, invitations=None):
        return SimpleNamespace(
            id=1,
            email='admin@example.com',
            es_superadmin=True,
            invitaciones_registro=invitations or [],
        )

    def test_invitar_registro_programa_n8n_en_background_sin_bloquear_respuesta(self):
        admin = self._admin()

        def find_one(model, query=None):
            if getattr(model, '__name__', '') == 'AdministradorPortal':
                return admin
            return None

        with patch('motor_firmas.views._mongo_find_one', side_effect=find_one), \
                patch('motor_firmas.views._mongo_update_document') as update_doc, \
                patch('motor_firmas.views._post_n8n_json_background') as background_post, \
                patch('motor_firmas.views.tracked_post') as tracked:
            response = admin_api(self._post_request(), 'invitar_registro')

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'success')
        self.assertTrue(payload['queued'])
        update_doc.assert_called_once()
        background_post.assert_called_once()
        self.assertEqual(background_post.call_args.args[1]['email'], 'alopez@consorcionova.com')
        tracked.assert_not_called()

    def test_invitar_registro_no_envia_correo_si_alopez_ya_existe(self):
        admin = self._admin()

        def find_one(model, query=None):
            model_name = getattr(model, '__name__', '')
            if model_name == 'AdministradorPortal':
                return admin
            if model_name == 'DirectorioFirmas':
                return SimpleNamespace(email='alopez@consorcionova.com')
            return None

        with patch('motor_firmas.views._mongo_find_one', side_effect=find_one), \
                patch('motor_firmas.views._mongo_update_document') as update_doc, \
                patch('motor_firmas.views._post_n8n_json_background') as background_post:
            response = admin_api(self._post_request(), 'invitar_registro')

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['already_registered'])
        update_doc.assert_not_called()
        background_post.assert_not_called()

    def test_invitar_registro_reintento_reciente_no_duplica_webhook(self):
        admin = self._admin([{
            'email': 'alopez@consorcionova.com',
            'requested_at': timezone.now().replace(tzinfo=None),
        }])

        def find_one(model, query=None):
            if getattr(model, '__name__', '') == 'AdministradorPortal':
                return admin
            return None

        with patch('motor_firmas.views._mongo_find_one', side_effect=find_one), \
                patch('motor_firmas.views._mongo_update_document') as update_doc, \
                patch('motor_firmas.views._post_n8n_json_background') as background_post:
            response = admin_api(self._post_request(), 'invitar_registro')

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['duplicate'])
        update_doc.assert_not_called()
        background_post.assert_not_called()

    def test_invitar_registro_rechaza_correo_invalido(self):
        admin = self._admin()

        with patch('motor_firmas.views._mongo_find_one', return_value=admin), \
                patch('motor_firmas.views._post_n8n_json_background') as background_post:
            response = admin_api(self._post_request('correo-invalido'), 'invitar_registro')

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Correo inválido', payload['error'])
        background_post.assert_not_called()


class PdfsUsuarioDedupeTest(SimpleTestCase):
    def test_oculta_duplicados_legacy_del_mismo_intento(self):
        base = timezone.now().replace(tzinfo=None)
        docs = [
            SimpleNamespace(
                id_documento='nuevo',
                nombre='scaner@raloy.com.mx_20260724_113548.pdf',
                drive_file_id='drive-nuevo',
                enviado_a_firma=False,
                converted_to_master=False,
                created_at=base,
            ),
            SimpleNamespace(
                id_documento='viejo',
                nombre='scaner@raloy.com.mx_20260724_113548.pdf',
                drive_file_id='drive-viejo',
                enviado_a_firma=False,
                converted_to_master=False,
                created_at=base - timedelta(minutes=20),
            ),
        ]

        visibles = _deduplicar_pdfs_usuario_visibles(docs)

        self.assertEqual([doc.id_documento for doc in visibles], ['nuevo'])

    def test_no_oculta_archivos_legacy_con_mismo_nombre_fuera_de_ventana(self):
        base = timezone.now().replace(tzinfo=None)
        docs = [
            SimpleNamespace(
                id_documento='nuevo',
                nombre='contrato.pdf',
                drive_file_id='drive-nuevo',
                enviado_a_firma=False,
                converted_to_master=False,
                created_at=base,
            ),
            SimpleNamespace(
                id_documento='anterior',
                nombre='contrato.pdf',
                drive_file_id='drive-anterior',
                enviado_a_firma=False,
                converted_to_master=False,
                created_at=base - timedelta(days=7),
            ),
        ]

        visibles = _deduplicar_pdfs_usuario_visibles(docs)

        self.assertEqual([doc.id_documento for doc in visibles], ['nuevo', 'anterior'])


class IniciarFirmaLibreIdempotenciaTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _post_request(self):
        request = self.factory.post(
            '/api/iniciar-firma-libre/',
            data=json.dumps({
                'pdf_id': 'pdf-123',
                'firmantes': [{'nombre': 'Uno', 'email': 'uno@example.com', 'orden': 1}],
            }),
            content_type='application/json',
        )
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session['owner_email'] = 'alopez@consorcionova.com'
        return request

    def test_reintento_de_firma_ya_enviada_no_vuelve_a_mandar_correo(self):
        doc = SimpleNamespace(
            id_documento='pdf-123',
            owner_email='alopez@consorcionova.com',
            enviado_a_firma=True,
            converted_to_master=True,
            proceso_reference_id='LIBRE-123',
            drive_file_id='drive-file-123',
            upload_status='uploaded',
        )

        with patch('motor_firmas.views._mongo_find_one_by_uuid_field', return_value=doc), \
                patch('motor_firmas.views.tracked_post') as tracked:
            response = iniciar_firma_libre(self._post_request())

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'success')
        self.assertTrue(payload['already_started'])
        self.assertEqual(payload['reference_id'], 'LIBRE-123')
        tracked.assert_not_called()

    def test_reintento_mientras_firma_esta_en_proceso_no_vuelve_a_mandar_correo(self):
        doc = SimpleNamespace(
            id_documento='pdf-123',
            owner_email='alopez@consorcionova.com',
            enviado_a_firma=False,
            converted_to_master=False,
            firma_iniciando=True,
            firma_iniciando_at=timezone.now().replace(tzinfo=None),
            drive_file_id='drive-file-123',
            upload_status='uploaded',
        )

        with patch('motor_firmas.views._mongo_find_one_by_uuid_field', return_value=doc), \
                patch('motor_firmas.views.tracked_post') as tracked:
            response = iniciar_firma_libre(self._post_request())

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(payload['status'], 'processing')
        self.assertTrue(payload['already_started'])
        tracked.assert_not_called()

    def test_firma_libre_no_inicia_si_pdf_sigue_pausado_en_drive(self):
        doc = SimpleNamespace(
            id_documento='pdf-123',
            owner_email='alopez@consorcionova.com',
            enviado_a_firma=False,
            converted_to_master=False,
            firma_iniciando=False,
            drive_file_id='',
            upload_status='paused',
        )

        with patch('motor_firmas.views._mongo_find_one_by_uuid_field', return_value=doc), \
                patch('motor_firmas.views.tracked_post') as tracked:
            response = iniciar_firma_libre(self._post_request())

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(payload['status'], 'paused')
        self.assertIn('resguardo externo', payload['error'])
        tracked.assert_not_called()

    def test_firma_libre_inicia_con_pdf_pendiente_de_n8n_si_existe_localmente(self):
        doc = SimpleNamespace(
            id_documento='pdf-123',
            owner_email='alopez@consorcionova.com',
            nombre='contrato.pdf',
            enviado_a_firma=False,
            converted_to_master=False,
            firma_iniciando=False,
            drive_file_id='',
            upload_status='pending_n8n',
        )
        proceso = SimpleNamespace(token_acceso='token-proceso')

        def find_one(model, query=None):
            if getattr(model, '__name__', '') == 'CarpetaDominio':
                return SimpleNamespace(drive_folder_id='drive-folder-raloy')
            return None

        with patch('motor_firmas.views._mongo_find_one_by_uuid_field', return_value=doc), \
                patch('motor_firmas.views._mongo_find_one', side_effect=find_one), \
                patch('motor_firmas.views._asegurar_pdf_usuario_local',
                      return_value=('pdfs_libres/original.pdf', '/tmp/original.pdf')), \
                patch('motor_firmas.views.shutil.copyfile'), \
                patch('motor_firmas.views._mongo_update_document'), \
                patch('motor_firmas.views._crear_proceso_firma_mongo', return_value=proceso) as crear_proceso, \
                patch('motor_firmas.views._post_n8n_json_background') as background_post, \
                patch('motor_firmas.views.crear_notificacion_firma'), \
                patch('motor_firmas.views._eliminar_archivo_media', return_value=True), \
                patch('motor_firmas.views.tracked_post') as tracked:
            response = iniciar_firma_libre(self._post_request())

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(crear_proceso.call_args.kwargs['summary_data']['source_upload_status'], 'pending_n8n')
        self.assertEqual(background_post.call_count, 2)
        tracked.assert_not_called()

    def test_firma_libre_exitosa_dispara_notificaciones_n8n_en_background(self):
        doc = SimpleNamespace(
            id_documento='pdf-123',
            owner_email='alopez@consorcionova.com',
            nombre='contrato.pdf',
            enviado_a_firma=False,
            converted_to_master=False,
            firma_iniciando=False,
            drive_file_id='drive-file-123',
            upload_status='uploaded',
        )
        proceso = SimpleNamespace(token_acceso='token-proceso')

        def find_one(model, query=None):
            if getattr(model, '__name__', '') == 'CarpetaDominio':
                return SimpleNamespace(drive_folder_id='drive-folder-raloy')
            return None

        with patch('motor_firmas.views._mongo_find_one_by_uuid_field', return_value=doc), \
                patch('motor_firmas.views._mongo_find_one', side_effect=find_one), \
                patch('motor_firmas.views._asegurar_pdf_usuario_local',
                      return_value=('pdfs_libres/original.pdf', '/tmp/original.pdf')), \
                patch('motor_firmas.views.shutil.copyfile'), \
                patch('motor_firmas.views._mongo_update_document'), \
                patch('motor_firmas.views._crear_proceso_firma_mongo', return_value=proceso) as crear_proceso, \
                patch('motor_firmas.views._post_n8n_json_background') as background_post, \
                patch('motor_firmas.views.crear_notificacion_firma'), \
                patch('motor_firmas.views._eliminar_archivo_media', return_value=True), \
                patch('motor_firmas.views.tracked_post') as tracked:
            response = iniciar_firma_libre(self._post_request())

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'success')
        self.assertIn('reference_id', payload)
        self.assertEqual(crear_proceso.call_args.kwargs['exec_mode'], 'libre')
        first_payload = background_post.call_args_list[0].args[1]
        self.assertIn('/firmar/token-proceso/', first_payload['link'])
        self.assertNotIn('firmx', first_payload['link'].lower())
        self.assertEqual(background_post.call_count, 2)
        tracked.assert_not_called()


class N8NMonitorGlobalEventsTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_monitor_admin_incluye_eventos_globales_de_otros_usuarios(self):
        request = self.factory.get('/api/n8n-monitor/events/')
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session['admin_email'] = 'pjimenezb@raloy.com.mx'
        global_event = {
            'id': 'global-1',
            'webhook_url': 'https://n8n.raloy.com.mx/webhook/subir-pdf-usuario',
            'webhook_label': '/webhook/subir-pdf-usuario',
            'ok': False,
            'decision': 'stop',
            'decision_label': 'FALLA - PARAR',
            'owner_email': 'alopez@consorcionova.com',
            'timestamp': '2026-07-24T12:00:00',
        }

        with patch('motor_firmas.views.session_can_view_monitor', return_value=True), \
                patch('motor_firmas.views._eventos_globales_n8n_monitor', return_value=[global_event]), \
                patch('motor_firmas.views.get_session_events', return_value=[]):
            response = n8n_monitor_events(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['events'][0]['id'], 'global-1')
        self.assertEqual(payload['events'][0]['owner_email'], 'alopez@consorcionova.com')


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
