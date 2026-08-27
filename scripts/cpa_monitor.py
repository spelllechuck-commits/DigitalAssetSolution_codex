import json,time,urllib.request,urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'docs/cpa/data'; DATA.mkdir(parents=True,exist_ok=True)
UA={'User-Agent':'CPA-Monitor/3.1.2'}
STABLE={'usdt','usdc','dai','fdusd','tusd','usde','usds','pyusd','frax','usdd','gusd','lusd','usdb','rlusd','usd1','usdg','usdf','usdy','usdp','usdk'}
EXCLUDED_IDS={'figure-heloc','usd1-wlfi','global-dollar'}
NAME_HINTS=('stablecoin','wrapped','bridged','staked ether','synthetic dollar')
def get(url,retries=2,timeout=8):
    for i in range(retries):
        try:return json.loads(urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=timeout).read().decode())
        except Exception:
            if i==retries-1:return None
            time.sleep(1.0*(i+1))
def excluded(c):
    n=c['name'].lower();s=c['symbol'].lower();return c.get('id') in EXCLUDED_IDS or s in STABLE or any(h in n for h in NAME_HINTS)
def universe():
    base='https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&sparkline=false&price_change_percentage=24h,7d,30d&per_page='
    with ThreadPoolExecutor(max_workers=2) as ex:
        fs=[ex.submit(get,base+'250&page=1'),ex.submit(get,base+'50&page=6')];a=fs[0].result() or [];b=fs[1].result() or []
    return sorted([x for x in a+b if x.get('market_cap_rank') and x['market_cap_rank']<=300],key=lambda x:x['market_cap_rank'])
def score(c,btc):
    d7=c.get('price_change_percentage_7d_in_currency') or 0; d30=c.get('price_change_percentage_30d_in_currency') or 0; d24=c.get('price_change_percentage_24h_in_currency') or 0
    vr=(c.get('total_volume') or 0)/(c.get('market_cap') or 1); rs=d7-(btc.get('price_change_percentage_7d_in_currency') or 0)
    pen=(8 if d24>12 else 0)+(10 if d7>35 else 0)+(8 if d30>85 else 0)
    s=50+min(15,d30*.22)+min(10,d7*.12)+min(10,vr*35)+max(-8,min(10,rs*.3))-pen
    return {'score':round(max(0,min(100,s))),'d7':d7,'d30':d30,'d24':d24,'rs':rs,'pen':pen,'vr':vr}
def ema(a,n):
    if len(a)<n:return None
    k=2/(n+1);v=sum(a[:n])/n
    for x in a[n:]:v=x*k+v*(1-k)
    return v
def rsi(a,n=14):
    if len(a)<=n:return None
    g=l=0
    for i in range(len(a)-n,len(a)):
        d=a[i]-a[i-1];g+=max(d,0);l+=max(-d,0)
    return 100 if l==0 else 100-100/(1+(g/n)/(l/n))
def _parse_bybit_klines(j):
    try:
        rows=j['result']['list'];rows=list(reversed(rows));return [float(x[4]) for x in rows]
    except Exception:return []
def enrich_binance(c):
    sym=c['symbol'].upper()+'USDT';out={'ok':False,'deriv':False,'source':'binance'}
    q=lambda u,p:get(u+'?'+urllib.parse.urlencode(p))
    reqs=[('d4','https://api.binance.com/api/v3/klines',{'symbol':sym,'interval':'4h','limit':220}),('dd','https://api.binance.com/api/v3/klines',{'symbol':sym,'interval':'1d','limit':220}),('prem','https://fapi.binance.com/fapi/v1/premiumIndex',{'symbol':sym}),('hist','https://fapi.binance.com/futures/data/openInterestHist',{'symbol':sym,'period':'1h','limit':25})]
    vals={}
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut={ex.submit(q,u,p):k for k,u,p in reqs}
        for f in as_completed(fut):vals[fut[f]]=f.result()
    d4,dd,prem,hist=vals.get('d4'),vals.get('dd'),vals.get('prem'),vals.get('hist')
    if isinstance(d4,list) and isinstance(dd,list):
        cd=[float(x[4]) for x in dd];c4=[float(x[4]) for x in d4];out.update(ok=True,e20=ema(cd,20),e50=ema(cd,50),e200=ema(cd,200),rsi=rsi(c4))
    if isinstance(prem,dict) and prem.get('lastFundingRate') is not None:out.update(deriv=True,funding=float(prem['lastFundingRate'])*100)
    if isinstance(hist,list) and len(hist)>1:
        f=float(hist[0]['sumOpenInterest']);l=float(hist[-1]['sumOpenInterest']);out.update(deriv=True,oi24=((l-f)/f*100 if f else None))
    return out
def enrich_bybit(c):
    sym=c['symbol'].upper()+'USDT';out={'ok':False,'deriv':False,'source':'bybit'}
    q=lambda p:get('https://api.bybit.com/v5/market/'+p[0]+'?'+urllib.parse.urlencode(p[1]))
    reqs=[('d4',('kline',{'category':'spot','symbol':sym,'interval':'240','limit':220})),('dd',('kline',{'category':'spot','symbol':sym,'interval':'D','limit':220})),('tick',('tickers',{'category':'linear','symbol':sym})),('oi',('open-interest',{'category':'linear','symbol':sym,'intervalTime':'1h','limit':25}))]
    vals={}
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut={ex.submit(q,p):k for k,p in reqs}
        for f in as_completed(fut):vals[fut[f]]=f.result()
    c4=_parse_bybit_klines(vals.get('d4'));cd=_parse_bybit_klines(vals.get('dd'))
    if len(c4)>=50 and len(cd)>=200:out.update(ok=True,e20=ema(cd,20),e50=ema(cd,50),e200=ema(cd,200),rsi=rsi(c4))
    try:
        t=vals['tick']['result']['list'][0];out.update(deriv=True,funding=float(t['fundingRate'])*100)
    except Exception:pass
    try:
        rows=vals['oi']['result']['list'];rows=list(reversed(rows));f=float(rows[0]['openInterest']);l=float(rows[-1]['openInterest']);out.update(deriv=True,oi24=((l-f)/f*100 if f else None))
    except Exception:pass
    return out
def enrich(c):
    b=enrich_binance(c)
    if b.get('ok') and b.get('deriv'):return b
    y=enrich_bybit(c)
    if y.get('ok') or y.get('deriv'):
        if not y.get('ok') and b.get('ok'):y.update({k:b.get(k) for k in ('e20','e50','e200','rsi')});y['ok']=True;y['source']='binance+bybit'
        if not y.get('deriv') and b.get('deriv'):y.update({k:b.get(k) for k in ('funding','oi24')});y['deriv']=True;y['source']='binance+bybit'
        return y
    return b
def classify(c,s,e):
    p=c['current_price'];tech_ok=bool(e.get('ok') and e.get('e20') and e.get('e50'));deriv_ok=bool(e.get('deriv'))
    if not tech_ok:return'UNVERIFIED'
    d=(p-e['e20'])/e['e20']*100
    if s['pen']>=10 or d>15 or (e.get('funding') is not None and e['funding']>.08) or (e.get('oi24') is not None and e['oi24']>25 and s['d7']>15):return'OVEREXTENDED'
    if p<e['e50']*.97:return'INVALIDATED'
    if abs(d)<=5 and e.get('rsi') is not None and e['rsi']<68 and deriv_ok and (e.get('funding') is None or e['funding']<.05):return'READY'
    if abs(d)<=9:return'NEAR ENTRY'
    return'WAIT'
def row(c,s,e=None,tier='OPPORTUNITY'):
    if e is None:return {'id':c['id'],'symbol':c['symbol'].upper(),'name':c['name'],'rank':c['market_cap_rank'],'price':c['current_price'],'tier':tier,'quality':s['score'],'status':'RADAR','d7':round(s['d7'],2),'d30':round(s['d30'],2),'rs':round(s['rs'],2)}
    st=classify(c,s,e);conf=min(100,45+(30 if e.get('ok') else 0)+(15 if e.get('deriv') else 0)+(10 if e.get('oi24') is not None else 0));final=s['score']-(5 if e.get('funding') is not None and e['funding']>.05 else 0)-(6 if e.get('oi24') is not None and e['oi24']>20 and s['d7']>10 else 0)+(4 if st=='READY' else 0)
    return {'id':c['id'],'symbol':c['symbol'].upper(),'name':c['name'],'rank':c['market_cap_rank'],'price':c['current_price'],'tier':tier,'quality':s['score'],'final':max(0,round(final)),'confidence':conf,'status':st,'data_source':e.get('source'),'d7':round(s['d7'],2),'d30':round(s['d30'],2),'rs':round(s['rs'],2),'funding':e.get('funding'),'oi24':e.get('oi24'),'e20':e.get('e20'),'e50':e.get('e50')}
def regime(coins):
    btc=next(x for x in coins if x['id']=='bitcoin');eth=next(x for x in coins if x['id']=='ethereum');alts=[x for x in coins if x['market_cap_rank']>10 and not excluded(x)];br=sum(1 for x in alts if (x.get('price_change_percentage_7d_in_currency') or 0)>0)/max(1,len(alts))*100
    s=round(max(0,min(100,50+max(-15,min(15,(btc.get('price_change_percentage_30d_in_currency') or 0)*.45))+max(-10,min(10,(eth.get('price_change_percentage_30d_in_currency') or 0)*.3))+(br-50)*.18)))
    return {'score':s,'name':'RISK-ON' if s>=80 else 'SELECTIVE RISK-ON' if s>=65 else 'NEUTRAL' if s>=50 else 'RISK-OFF' if s>=35 else 'DEFENSIVE','breadth':round(br,1)}
def meaningful(a,b):return bool(a and a!=b and f'{a}>{b}' in {'WAIT>NEAR ENTRY','WAIT>READY','NEAR ENTRY>READY','READY>INVALIDATED','READY>OVEREXTENDED','NEAR ENTRY>INVALIDATED','WAIT>INVALIDATED'})
def main():
    coins=universe()
    if not coins:raise SystemExit('market data unavailable')
    btc=next(x for x in coins if x['id']=='bitcoin');investable=[c for c in coins if not excluded(c)];core=investable[:25];opp=investable[25:100];disc=investable[100:300]
    scored={c['id']:score(c,btc) for c in investable};core_rows=[]
    with ThreadPoolExecutor(max_workers=8) as ex:
        fut={ex.submit(enrich,c):c for c in core}
        for f in as_completed(fut):
            c=fut[f];core_rows.append(row(c,scored[c['id']],f.result(),'CORE'))
    core_rows=sorted(core_rows,key=lambda x:x['rank']);opp_rows=[row(c,scored[c['id']],None,'OPPORTUNITY') for c in opp];opp_rows=sorted(opp_rows,key=lambda x:(x['quality'],x['rs'],x['d7']),reverse=True)[:15]
    promotions=[x for x in opp_rows if x['quality']>=60 and x['d30']>0 and x['rs']>0][:8]
    disc_candidates=[row(c,scored[c['id']],None,'DISCOVERY') for c in disc if scored[c['id']]['score']>=64 and scored[c['id']]['d30']>0 and scored[c['id']]['rs']>5];disc_candidates=sorted(disc_candidates,key=lambda x:x['quality'],reverse=True)[:10]
    sp=DATA/'monitor_state.json';prev={}
    if sp.exists():
        try:prev=json.loads(sp.read_text()).get('states',{})
        except Exception:pass
    states={r['id']:r['status'] for r in core_rows};alerts=[]
    for r in core_rows:
        old=prev.get(r['id'])
        if meaningful(old,r['status']):alerts.append({'id':r['id'],'symbol':r['symbol'],'name':r['name'],'from':old,'to':r['status'],'price':r['price'],'final':r['final'],'tier':'CORE'})
    verified=sum(1 for r in core_rows if r['status']!='UNVERIFIED');ready=sum(1 for r in core_rows if r['status']=='READY')
    result={'version':'3.1.2','updated_at':datetime.now(timezone.utc).isoformat(),'regime':regime(coins),'tiers':{'core_count':len(core),'opportunity_count':len(opp),'discovery_count':len(disc)},'data_quality':{'core_verified':verified,'core_unverified':len(core)-verified,'ready_count':ready},'core':core_rows,'opportunity':opp_rows,'promotions':promotions,'discovery':disc_candidates,'setups':core_rows,'alerts':alerts}
    (DATA/'latest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));sp.write_text(json.dumps({'updated_at':result['updated_at'],'states':states},ensure_ascii=False,indent=2));(DATA/'alerts.json').write_text(json.dumps(alerts,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
