from types import SimpleNamespace

from django.test import SimpleTestCase

from .views import (
    _indice_pendiente_actual,
    _indice_por_token,
    _indices_firmas_en_turno,
    _json_or_default,
)


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
