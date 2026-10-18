from __future__ import annotations

import logging
from logging.handlers import QueueHandler
from queue import Queue
import unittest

from Feedback.processors.redaction import SecretRedactingFormatter, redact_sensitive_text


class TestSecretRedaction(unittest.TestCase):
    def test_structured_credentials_are_removed_from_database_errors(self):
        text = "SQL parameters: {'api_key': 'sample-key', 'api_secret': 'sample-secret', 'password': 'two words'}"
        redacted = redact_sensitive_text(text)
        for secret in ('sample-key', 'sample-secret', 'two words'):
            self.assertNotIn(secret, redacted)
        self.assertIn('SQL parameters', redacted)

    def test_headers_url_passwords_and_query_secrets_are_removed(self):
        for text, secret in (
            ('Authorization: Bearer sample-bearer', 'sample-bearer'),
            ('https://example.com/?api_key=sample-query&status=ok', 'sample-query'),
            ('https://user:sample-password@example.com/', 'sample-password'),
            ('{"refresh_token": "sample-refresh"}', 'sample-refresh'),
        ):
            with self.subTest(text=text):
                self.assertNotIn(secret, redact_sensitive_text(text))

    def test_exception_traceback_is_redacted_before_it_enters_log_queue(self):
        queue = Queue()
        handler = QueueHandler(queue)
        handler.setFormatter(SecretRedactingFormatter('%(message)s'))
        logger = logging.Logger('redaction-test')
        logger.addHandler(handler)
        try:
            raise ValueError("parameters: {'api_secret': 'sample-exception-secret'}")
        except ValueError:
            logger.exception('Account save failed')
        record = queue.get_nowait()
        self.assertNotIn('sample-exception-secret', record.getMessage())
        self.assertIn('ValueError', record.getMessage())

    def test_nonsecret_diagnostics_are_preserved(self):
        self.assertEqual(redact_sensitive_text('GET /orders status=429 count=3'), 'GET /orders status=429 count=3')
