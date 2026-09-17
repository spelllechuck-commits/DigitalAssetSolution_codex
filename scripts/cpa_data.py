"""Bounded public-data collection. No API keys appear in URLs or diagnostics."""
import hashlib
import json
import math
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime


def retry_delay(value, now):
    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return None


class Client:
    def __init__(self, clock=time.time, sleep=time.sleep, opener=urllib.request.urlopen, budget=720):
        self.clock, self.sleep, self.opener = clock, sleep, opener
        self.deadline = clock() + budget
        self.next_request = {}
        self.blocked = {}
        self.errors = {}
        self.calls = {}
        self.lock = threading.Lock()

    def get(self, url, retries=3, timeout=12, headers=None):
        host = urllib.parse.urlsplit(url).netloc
        interval = 6 if 'coingecko' in host else 0.25
        with self.lock:
            if host in self.blocked:
                self.errors[url] = self.blocked[host]
                return None
            for attempt in range(retries):
                delay = max(0, self.next_request.get(host, 0) - self.clock())
                if self.clock() + delay + timeout > self.deadline:
                    self.errors[url] = 'BUDGET_EXHAUSTED'
                    return None
                if delay:
                    self.sleep(delay)
                self.next_request[host] = self.clock() + interval
                self.calls[host] = self.calls.get(host, 0) + 1
                try:
                    request = urllib.request.Request(url, headers={'User-Agent': 'CPA-Monitor/4.3', **(headers or {})})
                    with self.opener(request, timeout=timeout) as response:
                        result = json.loads(response.read().decode())
                    self.errors.pop(url, None)
                    return result
                except urllib.error.HTTPError as exc:
                    code = exc.code
                    reason = {429: 'RATE_LIMITED', 451: 'ACCESS_RESTRICTED', 403: 'FORBIDDEN',
                              401: 'AUTH_REQUIRED', 404: 'NOT_FOUND'}.get(code, 'HTTP_' + str(code))
                    self.errors[url] = reason
                    print(json.dumps({'provider': host, 'path': urllib.parse.urlsplit(url).path,
                                      'status': code, 'attempt': attempt + 1}), flush=True)
                    if code in (451, 403, 401):
                        self.blocked[host] = reason
                        return None
                    if code == 429:
                        wait = retry_delay(exc.headers.get('Retry-After'), self.clock())
                        wait = wait if wait is not None else 60 * (2 ** attempt) + random.uniform(0, 3)
                        self.next_request[host] = self.clock() + wait
                    elif code >= 500:
                        self.next_request[host] = self.clock() + 2 ** (attempt + 1)
                    else:
                        return None
                except (OSError, ValueError) as exc:
                    self.errors[url] = type(exc).__name__
                    self.next_request[host] = self.clock() + 2 ** (attempt + 1)
            return None


CLIENT = Client()


def coingecko(path, params):
    pro = os.environ.get('COINGECKO_PRO_API_KEY', '')
    demo = os.environ.get('COINGECKO_DEMO_API_KEY', '')
    root = 'https://pro-api.coingecko.com/api/v3' if pro else 'https://api.coingecko.com/api/v3'
    headers = {'x-cg-pro-api-key': pro} if pro else {'x-cg-demo-api-key': demo} if demo else {}
    return CLIENT.get(root + path + '?' + urllib.parse.urlencode(params), headers=headers)


def technical(coin, cache, fetch, ema, rsi, now=None):
    now = time.time() if now is None else now
    saved = cache.setdefault(coin['id'], {})
    # Existing aggregate caches cannot supply independently timestamped histories.
    components = saved.setdefault('components', {})
    jitter = int(hashlib.sha256(coin['id'].encode()).hexdigest()[:4], 16) % 600
    statuses = {}
    for key, params, minimum, ttl, age_limit in (
        ('daily', {'days': '365', 'interval': 'daily'}, 200, 86400-jitter, 172800),
        ('intraday', {'days': '30'}, 81, 7200-jitter, 21600),
    ):
        part = components.get(key, {})
        # Validate the source timestamp again on cache hits, not just insertion.
        try:
            fresh = (0 <= now - part['fetched_at'] < ttl
                     and -300 <= now - part['prices'][-1][0]/1000 <= age_limit)
        except (KeyError, IndexError, TypeError):
            fresh = False
        refresh = not fresh
        statuses[key] = 'CACHE'
        if refresh:
            result = fetch('/coins/' + coin['id'] + '/market_chart', {'vs_currency': 'usd', **params})
            prices = result.get('prices') if isinstance(result, dict) else None
            try:
                clean = [[float(t), float(v)] for t, v in prices]
                valid = len(clean) >= minimum and all(math.isfinite(t) and math.isfinite(v) and v > 0 for t, v in clean)
                valid = valid and all(clean[i][0] < clean[i+1][0] for i in range(len(clean)-1))
                valid = valid and -300 <= now - clean[-1][0]/1000 <= age_limit
            except (TypeError, ValueError):
                valid = False
            if valid:
                part = {'prices': clean, 'fetched_at': now}
                components[key] = part  # Preserve success even if the other component fails.
                statuses[key] = 'LIVE'
            else:
                statuses[key] = 'FETCH_FAILED' if prices is None else 'INVALID_OR_SHORT_HISTORY'
        if statuses[key] not in ('CACHE', 'LIVE'):
            statuses[key] = 'STALE' if part else statuses[key]
    usable = all(k in components and statuses[k] in ('CACHE', 'LIVE') for k in ('daily', 'intraday'))
    source = 'coingecko-live' if 'LIVE' in statuses.values() else 'coingecko-cache' if usable else 'coingecko-unavailable'
    out = {'ok': False, 'source': source, 'technical_components': statuses}
    if usable:
        daily = [p[1] for p in components['daily']['prices']]
        four = [p[1] for p in components['intraday']['prices']][::4]
        out.update(ok=True, e20=ema(daily,20), e50=ema(daily,50), e200=ema(daily,200),
                   rsi=rsi(four), four_last=four[-1], four_prev=four[-2], four_prev2=four[-3], ts=now)
        saved.update({k: out[k] for k in ('ok','e20','e50','e200','rsi','four_last','four_prev','four_prev2','ts')})
    # No expired aggregate fallback; stale prices never become fresh signals.
    return out
