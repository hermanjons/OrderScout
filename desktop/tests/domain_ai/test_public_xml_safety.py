from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from defusedxml.common import DefusedXmlException
from AI.processors import tools


class TestPublicXmlSafety(unittest.TestCase):
    def test_search_feeds_reject_xml_entity_definitions(self):
        payload = (
            b'<!DOCTYPE rss [<!ENTITY expansion "synthetic-content">]>'
            b'<rss><channel><item><title>&expansion;</title>'
            b'<link>https://example.com/</link></item></channel></rss>'
        )
        for search in (tools._bing_rss_search, tools._google_news_rss_search):
            with self.subTest(provider=search.__name__):
                with patch.object(tools.urllib.request, 'urlopen', return_value=io.BytesIO(payload)):
                    with self.assertRaises(DefusedXmlException):
                        search('synthetic public query', limit=1)
