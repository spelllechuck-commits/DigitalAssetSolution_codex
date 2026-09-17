"""Read-only provider discovery on the production runner; never place orders."""
import json
import urllib.request
import urllib.error

ENDPOINTS = {
    'kraken': 'https://futures.kraken.com/derivatives/api/v3/tickers',
    'bybit': 'https://api.bybit.com/v5/market/tickers?category=linear',
}


def main():
    for provider, url in ENDPOINTS.items():
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                data = json.load(response)
            rows = data.get('tickers', []) if provider == 'kraken' else data.get('result', {}).get('list', [])
            samples = [r for r in rows if r.get('symbol') in ('PF_XBTUSD','PF_BTCUSD','BTCUSDT','ETHUSDT','PF_ETHUSD')]
            print(json.dumps({'probe': provider, 'result': data.get('result') if provider=='kraken' else data.get('retCode'),
                              'count': len(rows), 'samples': samples}), flush=True)
        except urllib.error.HTTPError as exc:
            print(json.dumps({'probe': provider, 'http_status': exc.code}), flush=True)
        except Exception as exc:
            print(json.dumps({'probe': provider, 'error': type(exc).__name__}), flush=True)


if __name__ == '__main__':
    main()
