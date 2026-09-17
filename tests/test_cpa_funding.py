import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cpa_funding import Funding, timestamp


class FundingTests(unittest.TestCase):
    def setup_provider(self, rate=0.00001, time='2026-09-17T01:00:00Z', previous='2026-09-17T00:00:00Z'):
        ticker = {'symbol': 'PF_XBTUSD', 'pair': 'XBT:USD', 'tag': 'perpetual', 'suspended': False, 'fundingRate': 999}
        history = {'result': 'success', 'rates': [
            {'timestamp': previous, 'relativeFundingRate': rate},
            {'timestamp': time, 'relativeFundingRate': rate}]}
        client = Mock(errors={})
        client.get.side_effect = [{'result': 'success', 'tickers': [ticker]}, history, history]
        return Funding(client, lambda: timestamp('2026-09-17T01:30:00Z')), client

    def test_relative_rate_normalization_and_one_catalog_fetch(self):
        provider, client = self.setup_provider()
        for _ in range(2):
            result = provider.get({'id': 'bitcoin', 'symbol': 'WRONG'})
            self.assertAlmostEqual(result['funding'], 0.008)
            self.assertTrue(result['deriv'])
            self.assertEqual(result['funding_meta']['instrument'], 'PF_XBTUSD')
        self.assertEqual(client.get.call_count, 3)

    def test_zero_negative_and_invalid_rates(self):
        for rate in (0, -0.00001):
            provider, _ = self.setup_provider(rate)
            self.assertTrue(provider.get({'id': 'bitcoin'})['deriv'])
        for rate in (None, float('nan'), float('inf'), True):
            provider, _ = self.setup_provider(rate)
            self.assertFalse(provider.get({'id': 'bitcoin'})['deriv'])

    def test_stale_future_and_nonhourly_rates_are_missing(self):
        for when, previous in [('2026-09-16T23:00:00Z', '2026-09-16T22:00:00Z'),
                               ('2026-09-17T02:00:00Z', '2026-09-17T01:00:00Z'),
                               ('2026-09-17T01:00:00Z', '2026-09-16T21:00:00Z')]:
            provider, _ = self.setup_provider(time=when, previous=previous)
            self.assertIsNone(provider.get({'id': 'bitcoin'})['funding'])

    def test_symbol_collision_and_access_error_stay_missing(self):
        provider, client = self.setup_provider()
        self.assertEqual(provider.get({'id': 'other-bitcoin', 'symbol': 'BTC'})['funding_meta']['status'], 'UNMAPPED_ASSET')
        client.get.assert_not_called()
        client.get.side_effect = None
        client.get.return_value = None
        for coin in ('bitcoin', 'ethereum'):
            self.assertFalse(provider.get({'id': coin})['deriv'])
        self.assertEqual(client.get.call_count, 1)
