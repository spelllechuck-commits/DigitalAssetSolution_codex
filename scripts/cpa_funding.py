"""Kraken public funding, explicitly mapped and normalized to percent per 8h.

Use relativeFundingRate from historical rates, never the absolute ticker rate.
The latest hourly rate is extrapolated, not a realised eight-hour payment.
"""
from datetime import datetime
import math
import time
from urllib.parse import urlencode

ROOT = 'https://futures.kraken.com/derivatives/api/v3'
# CoinGecko IDs, not ambiguous display symbols. Unknown assets remain missing.
ASSETS = {
    'bitcoin': 'XBT', 'ethereum': 'ETH', 'binancecoin': 'BNB', 'ripple': 'XRP',
    'solana': 'SOL', 'tron': 'TRX', 'zcash': 'ZEC', 'hyperliquid': 'HYPE',
    'dogecoin': 'DOGE', 'monero': 'XMR', 'chainlink': 'LINK', 'cardano': 'ADA',
    'stellar': 'XLM', 'bitcoin-cash': 'BCH', 'uniswap': 'UNI', 'litecoin': 'LTC',
    'canton-network': 'CC', 'the-open-network': 'TON', 'near': 'NEAR',
    'avalanche-2': 'AVAX', 'hedera-hashgraph': 'HBAR', 'shiba-inu': 'SHIB',
}


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Funding timestamps must include a timezone')
    return result.timestamp()


class Funding:
    def __init__(self, client, clock=time.time):
        self.client, self.clock = client, clock
        self.tickers = None
        self.snapshot_error = None

    def get(self, coin):
        base = ASSETS.get(coin['id'])
        meta = {'source': 'kraken', 'status': 'UNMAPPED_ASSET', 'unit': 'percent',
                'normalized_period_hours': 8, 'source_period_hours': 1,
                'basis': 'latest_historical_hourly_rate_8h_equivalent'}
        out = {'deriv': False, 'funding': None, 'funding_meta': meta}
        if not base:
            return out
        if self.tickers is None:
            url = ROOT + '/tickers'
            payload = self.client.get(url, retries=2, timeout=10)
            valid = isinstance(payload, dict) and payload.get('result') == 'success' and isinstance(payload.get('tickers'), list)
            self.tickers = {r.get('symbol'): r for r in payload['tickers'] if isinstance(r, dict)} if valid else {}
            self.snapshot_error = None if valid else self.client.errors.get(url, 'INVALID_RESPONSE')
        symbol = 'PF_' + base + 'USD'
        meta['instrument'] = symbol
        ticker = self.tickers.get(symbol)
        if self.snapshot_error:
            meta['status'] = self.snapshot_error
            return out
        if not ticker:
            meta['status'] = 'NO_LISTED_CONTRACT'
            return out
        if ticker.get('suspended') is not False or ticker.get('tag') != 'perpetual' or ticker.get('pair') != base + ':USD':
            meta['status'] = 'INACTIVE_OR_MISMATCHED_CONTRACT'
            return out
        url = ROOT + '/historical-funding-rates?' + urlencode({'symbol': symbol})
        payload = self.client.get(url, retries=2, timeout=10)
        if not isinstance(payload, dict) or payload.get('result') != 'success':
            meta['status'] = self.client.errors.get(url, 'INVALID_RESPONSE')
            return out
        try:
            rates = sorted(payload['rates'], key=lambda x: timestamp(x['timestamp']))
            latest, previous = rates[-1], rates[-2]
            when = timestamp(latest['timestamp'])
            # Refuse a changed/unknown funding interval instead of assuming 8h.
            if abs(when - timestamp(previous['timestamp']) - 3600) > 1:
                meta['status'] = 'UNVERIFIED_INTERVAL'
                return out
            if not 0 <= self.clock() - when <= 7200:
                meta['status'] = 'STALE_OR_FUTURE'
                return out
            rate = float(latest['relativeFundingRate'])
            if not math.isfinite(rate) or isinstance(latest['relativeFundingRate'], bool):
                raise ValueError('Invalid rate')
            funding = rate * 8 * 100
            if not math.isfinite(funding):
                raise ValueError('Invalid normalized rate')
        except (KeyError, IndexError, TypeError, ValueError, OverflowError, AttributeError):
            meta['status'] = 'INVALID_RESPONSE'
            return out
        meta.update(status='VERIFIED', observed_at=latest['timestamp'], raw_relative_rate=rate)
        out.update(deriv=True, funding=funding)
        return out
