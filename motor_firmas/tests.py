from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from . import utils
from .views import (
    _indice_pendiente_actual,
    _indice_por_token,
    _indices_firmas_en_turno,
    _json_or_default,
)


class FakeMongoCollection:
    def __init__(self, documents=None):
        self.documents = documents or []

    def _matches(self, document, query):
        return all(document.get(key) == value for key, value in query.items())

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

    def insert_one(self, document):
        self.documents.append(document)


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
