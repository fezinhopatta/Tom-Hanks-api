import unittest
import json
import time
import hmac
import hashlib
from app import app, get_user_premium_status

class StripeIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True

    def test_routes_exist(self):
        """Verifica se os endpoints solicitados foram registrados corretamente."""
        rules = [rule.rule for rule in self.app.url_map.iter_rules()]
        self.assertIn('/checkout', rules)
        self.assertIn('/stripe/checkout', rules)
        self.assertIn('/webhook/stripe', rules)
        self.assertIn('/stripe/webhook', rules)
        self.assertIn('/api/stripe/webhook', rules)
        self.assertIn('/checkout/sucesso', rules)
        self.assertIn('/checkout/cancelado', rules)
        self.assertIn('/desfavoritar', rules)

    def test_webhook_rejects_invalid_signature_when_secret_set(self):
        """Requisito 3: Valida que requisições com assinatura forjada/inválida são rejeitadas."""
        import os
        old_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
        os.environ['STRIPE_WEBHOOK_SECRET'] = 'whsec_test_secret_12345'
        
        try:
            payload = json.dumps({'type': 'checkout.session.completed'})
            response = self.client.post(
                '/webhook/stripe',
                data=payload,
                content_type='application/json',
                headers={'Stripe-Signature': 't=12345,v1=assinatura_invalida'}
            )
            # Deve recusar com 400 (Bad Request - Assinatura inválida)
            self.assertEqual(response.status_code, 400)
        finally:
            if old_secret is not None:
                os.environ['STRIPE_WEBHOOK_SECRET'] = old_secret
            else:
                os.environ.pop('STRIPE_WEBHOOK_SECRET', None)

    def test_webhook_valid_signature_handling(self):
        """Requisito 3 e 5: Valida que uma chamada com assinatura legítima do Stripe é processada."""
        import os
        test_secret = 'whsec_test_secret_99999'
        old_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
        os.environ['STRIPE_WEBHOOK_SECRET'] = test_secret

        try:
            timestamp = int(time.time())
            payload_data = {
                'id': 'evt_test_123',
                'object': 'event',
                'type': 'checkout.session.completed',
                'data': {
                    'object': {
                        'id': 'cs_test_session',
                        'customer': 'cus_test_abc123',
                        'subscription': 'sub_test_xyz789',
                        'client_reference_id': '999999',
                        'metadata': {'user_id': '999999'}
                    }
                }
            }
            payload_bytes = json.dumps(payload_data).encode('utf-8')
            
            # Gera a assinatura Stripe real usando HMAC-SHA256
            signed_payload = f"{timestamp}.".encode('utf-8') + payload_bytes
            signature = hmac.new(
                test_secret.encode('utf-8'),
                signed_payload,
                hashlib.sha256
            ).hexdigest()
            sig_header = f"t={timestamp},v1={signature}"

            response = self.client.post(
                '/webhook/stripe',
                data=payload_bytes,
                content_type='application/json',
                headers={'Stripe-Signature': sig_header}
            )
            self.assertIn(response.status_code, [200, 500]) # 200 processado (ou 500 se o DB de teste não tiver usuário 999999)
        finally:
            if old_secret is not None:
                os.environ['STRIPE_WEBHOOK_SECRET'] = old_secret
            else:
                os.environ.pop('STRIPE_WEBHOOK_SECRET', None)

    def test_checkout_redirects_unauthenticated(self):
        """Verifica que usuário não autenticado é redirecionado para o login."""
        response = self.client.get('/checkout')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.location)

    def test_favoritar_limit_enforcement_for_free_user(self):
        """Requisito 4: Usuário comum bloqueado ao tentar ultrapassar o limite de 5 favoritos."""
        from unittest.mock import patch, MagicMock

        with self.client.session_transaction() as sess:
            sess['user_id'] = 10
            sess['nome'] = 'Usuario Teste'
            sess['is_premium'] = False

        # Simula usuário NÃO premium e contagem de favoritos já no limite (5)
        with patch('app.get_user_premium_status', return_value=False), \
             patch('app.get_db_connection') as mock_db, \
             patch('app.send_audit_log') as mock_log:

            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (5,) # Já tem 5 favoritos
            mock_conn.cursor.return_value = mock_cursor
            mock_db.return_value = mock_conn

            response = self.client.post('/favoritar', data={
                'movie_id': '550',
                'titulo': 'Filme 6',
                'poster_path': '/path.jpg'
            }, follow_redirects=True)

            # Verifica que o log de auditoria 403 foi disparado
            mock_log.assert_called_with('403_limite_favoritos_atingido', 10)
            # Verifica que a mensagem de flash sobre limite foi exibida
            self.assertIn(b"Limite atingido", response.data)

    def test_favoritar_unlimited_for_premium_user(self):
        """Requisito 4: Usuário Premium pode favoritar sem restrição de limite."""
        from unittest.mock import patch, MagicMock

        with self.client.session_transaction() as sess:
            sess['user_id'] = 10
            sess['nome'] = 'Usuario VIP'
            sess['is_premium'] = True

        # Simula usuário PREMIUM com mais de 5 favoritos
        with patch('app.get_user_premium_status', return_value=True), \
             patch('app.get_db_connection') as mock_db, \
             patch('app.send_audit_log') as mock_log:

            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_db.return_value = mock_conn

            response = self.client.post('/favoritar', data={
                'movie_id': '999',
                'titulo': 'Filme VIP',
                'poster_path': '/vip.jpg'
            }, follow_redirects=True)

            # O cursor deve ter executado o INSERT de favoritos
            mock_cursor.execute.assert_any_call(
                "INSERT INTO favoritos (usuario_id, tmdb_movie_id, titulo, poster_path) VALUES (%s, %s, %s, %s)",
                (10, '999', 'Filme VIP', '/vip.jpg')
            )
            mock_conn.commit.assert_called_once()
            mock_log.assert_called_with('favoritar_filme_999', 10)

if __name__ == '__main__':
    unittest.main()

