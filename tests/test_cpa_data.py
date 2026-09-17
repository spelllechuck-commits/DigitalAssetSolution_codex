import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cpa_data import Client, technical, retry_delay


class Clock:
    def __init__(self): self.now = 1000000
    def time(self): return self.now
    def sleep(self, seconds): self.now += seconds


def response():
    obj = Mock()
    obj.__enter__ = Mock(return_value=obj)
    obj.__exit__ = Mock(return_value=False)
    obj.read.return_value = b'{}'
    return obj


class DataTests(unittest.TestCase):
    def test_retry_after_and_spacing(self):
        c = Clock()
        opener = Mock(side_effect=[urllib.error.HTTPError('x',429,'limited',{'Retry-After':'65'},None),response()])
        client = Client(c.time,c.sleep,opener)
        self.assertEqual(client.get('https://api.coingecko.com/x'), {})
        self.assertEqual(c.now,1000065)
        self.assertEqual(opener.call_count,2)

    def test_restricted_provider_is_not_retried(self):
        c = Clock(); opener = Mock(side_effect=urllib.error.HTTPError('x',451,'restricted',{},None))
        client = Client(c.time,c.sleep,opener)
        client.get('https://example.com/a');client.get('https://example.com/b')
        self.assertEqual(opener.call_count,1)
        self.assertEqual(client.errors['https://example.com/b'],'ACCESS_RESTRICTED')

    def test_long_retry_after_respects_budget(self):
        c = Clock();opener = Mock(side_effect=urllib.error.HTTPError('x',429,'limited',{'Retry-After':'3600'},None))
        client = Client(c.time,c.sleep,opener,budget=60)
        self.assertIsNone(client.get('https://example.com/a'))
        self.assertEqual(opener.call_count,1)
        self.assertEqual(c.now,1000000)

    def test_partial_cache_is_reused_and_expired_is_not_verified(self):
        now=10000000;prices={'prices':[[1000*(now-(365-i)*86400),100+i] for i in range(366)]}
        hourly={'prices':[[1000*(now-(720-i)*3600),100+i] for i in range(721)]}
        cache={};fetch=Mock(side_effect=[prices,None]);ema=lambda a,n: sum(a[-n:])/n;rsi=lambda a:50
        first=technical({'id':'coin'},cache,fetch,ema,rsi,now)
        self.assertFalse(first['ok']);self.assertIn('daily',cache['coin']['components'])
        fetch=Mock(return_value=hourly)
        second=technical({'id':'coin'},cache,fetch,ema,rsi,now+60)
        self.assertTrue(second['ok']);self.assertEqual(fetch.call_count,1)
        failed=technical({'id':'coin'},cache,Mock(return_value=None),ema,rsi,now+90000)
        self.assertFalse(failed['ok'])

    def test_http_date_retry_after(self):
        self.assertEqual(retry_delay('Thu, 01 Jan 1970 00:01:00 GMT',0),60)
        self.assertIsNone(retry_delay('invalid',0))
