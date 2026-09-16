import json,time,urllib.request,urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from cpa_calibration import update_calibration
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'docs/cpa/data';DATA.mkdir(parents=True,exist_ok=True)
CACHE_PATH=DATA/'tech_cache.json';EVENT_PATH=DATA/'market_events.json';PERF_PATH=DATA/'performance_history.json'
UA={'User-Agent':'CPA-Monitor/4.2'};STABLE={'usdt','usdc','dai','fdusd','tusd','usde','usds','pyusd','frax','usdd','gusd','lusd','usdb','rlusd','usd1','usdg','usdf','usdy','usdp','usdk'};EXCLUDED_IDS={'figure-heloc','usd1-wlfi','global-dollar'};NAME_HINTS=('stablecoin','wrapped','bridged','staked ether','synthetic dollar');EVENT_BASE={'ETF':3,'ADOPTION':2,'REGULATION':2.5,'HACK':4,'DEPEG':5,'EXCHANGE':3.5,'MACRO':2.5,'PRICE':1.5,'OTHER':1};SEV={'LOW':.5,'MEDIUM':1,'HIGH':1.5,'CRITICAL':2}
def get(url,retries=3,timeout=12):
 for i in range(retries):
  try:return json.loads(urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=timeout).read().decode())
  except Exception:
   if i==retries-1:return None
   time.sleep(2*(i+1))
def load_json(p,d):
 try:return json.loads(p.read_text()) if p.exists() else d
 except:return d
def excluded(c):return c.get('id') in EXCLUDED_IDS or c['symbol'].lower() in STABLE or any(h in c['name'].lower() for h in NAME_HINTS)
def cg(path,p):return get('https://api.coingecko.com/api/v3'+path+'?'+urllib.parse.urlencode(p))
def universe():
 p={'vs_currency':'usd','order':'market_cap_desc','sparkline':'false','price_change_percentage':'24h,7d,30d'}
 with ThreadPoolExecutor(max_workers=2) as ex:a=ex.submit(cg,'/coins/markets',{**p,'per_page':250,'page':1}).result() or [];b=ex.submit(cg,'/coins/markets',{**p,'per_page':50,'page':6}).result() or []
 return sorted([x for x in a+b if x.get('market_cap_rank') and x['market_cap_rank']<=300],key=lambda x:x['market_cap_rank'])
def score(c,btc):
 d7=c.get('price_change_percentage_7d_in_currency') or 0;d30=c.get('price_change_percentage_30d_in_currency') or 0;d24=c.get('price_change_percentage_24h_in_currency') or 0;vr=(c.get('total_volume') or 0)/(c.get('market_cap') or 1);rs=d7-(btc.get('price_change_percentage_7d_in_currency') or 0);pen=(8 if d24>12 else 0)+(10 if d7>35 else 0)+(8 if d30>85 else 0);v=50+min(15,d30*.22)+min(10,d7*.12)+min(10,vr*35)+max(-8,min(10,rs*.3))-pen;return{'score':round(max(0,min(100,v))),'d7':d7,'d30':d30,'d24':d24,'rs':rs,'pen':pen}
def ema(a,n):
 if len(a)<n:return None
 k=2/(n+1);v=sum(a[:n])/n
 for x in a[n:]:v=x*k+v*(1-k)
 return v
def rsi(a,n=14):
 if len(a)<=n:return None
 ds=[a[i]-a[i-1] for i in range(len(a)-n,len(a))];g=sum(max(x,0) for x in ds)/n;l=sum(max(-x,0) for x in ds)/n;return 100 if l==0 else 100-100/(1+g/l)
def tech(c,cache):
 now=time.time();old=cache.get(c['id']) or {};age=now-float(old.get('ts',0) or 0)
 if old.get('ok') and age<7200:return {**old,'source':'coingecko-cache'}
 out={'ok':False,'source':'coingecko-live'};d=cg(f"/coins/{c['id']}/market_chart",{'vs_currency':'usd','days':'365','interval':'daily'});time.sleep(1.1);h=cg(f"/coins/{c['id']}/market_chart",{'vs_currency':'usd','days':'30'});time.sleep(1.1)
 try:
  daily=[float(x[1]) for x in d['prices']];four=[float(x[1]) for x in h['prices']][::4]
  if len(daily)>=200 and len(four)>20:out.update(ok=True,e20=ema(daily,20),e50=ema(daily,50),e200=ema(daily,200),rsi=rsi(four),four_last=four[-1],four_prev=four[-2],four_prev2=four[-3],ts=now)
 except:pass
 if out.get('ok'):cache[c['id']]={k:out.get(k) for k in ('ok','e20','e50','e200','rsi','four_last','four_prev','four_prev2','ts')};return out
 if old.get('ok') and age<86400:return {**old,'source':'coingecko-stale-cache'}
 return out
def deriv(c):
 sym=c['symbol'].upper()+'USDT';p=get('https://fapi.binance.com/fapi/v1/premiumIndex?'+urllib.parse.urlencode({'symbol':sym}),retries=1,timeout=5);o={'deriv':False}
 if isinstance(p,dict) and p.get('lastFundingRate') is not None:o.update(deriv=True,funding=float(p['lastFundingRate'])*100)
 return o
def active_events():
 f=load_json(EVENT_PATH,{'market_risk':'LOW','events':[]});now=datetime.now(timezone.utc);seen=set();a=[]
 for e in f.get('events',[]):
  if e.get('id') in seen:continue
  try:
   if e.get('expires_at') and datetime.fromisoformat(e['expires_at'].replace('Z','+00:00'))<=now:continue
  except:pass
  seen.add(e.get('id'));a.append(e)
 return f.get('market_risk','LOW'),a
def event_symbols(e):return [str(x).upper() for x in(e.get('affected_symbols') or e.get('affected') or [])]
def decay(e):
 try:a=(datetime.now(timezone.utc)-datetime.fromisoformat(e['timestamp'].replace('Z','+00:00'))).total_seconds()/86400
 except:return .4
 return 1 if a<=1 else .7 if a<=3 else .4 if a<=7 else .15
def evval(e):return (1 if e.get('direction')=='POSITIVE' else -1 if e.get('direction')=='NEGATIVE' else 0)*EVENT_BASE.get(e.get('type'),1)*SEV.get(e.get('severity'),1)*decay(e)
def overlay(st,sym,events,risk):
 es=[e for e in events if e.get('scope')=='MARKET' or sym in event_symbols(e)];net=sum(evval(e) for e in es);high=any(evval(e)<=-4 and e.get('confidence')=='HIGH' for e in es);base=st
 if(high or risk in('HIGH','CRITICAL')) and st in('NEAR ENTRY','CONFIRMED','READY'):st='EVENT HOLD'
 return st,{'base_status':base,'event_score':round(net,2),'event_risk':'HIGH' if high else'MEDIUM' if net<-1 else'LOW','catalyst':'POSITIVE' if net>1 else'NEGATIVE' if net<-1 else'NEUTRAL','events':sorted(es,key=lambda e:abs(evval(e)),reverse=True)[:4]}
def classify(c,s,e):
 p=c['current_price'];ok=e.get('ok') and e.get('e20') and e.get('e50') and e.get('rsi') is not None
 if not ok:return'UNVERIFIED'
 d=(p-e['e20'])/e['e20']*100
 if s['pen']>=10 or d>15:return'OVEREXTENDED'
 if p<e['e50']*.97:return'INVALIDATED'
 if abs(d)<=9:return'NEAR ENTRY'
 return'WAIT'
def confirm(c,s,e,base):
 if base!='NEAR ENTRY':return base,0,[]
 checks=[];p=c['current_price'];e20=e.get('e20');r=e.get('rsi');f=e.get('funding');a=e.get('four_last');b=e.get('four_prev');cc=e.get('four_prev2')
 if e20 and p>=e20*.985:checks.append('20EMA support')
 if r is not None and 40<=r<=65:checks.append('RSI balanced')
 if a and b and cc and a>b and b>=cc*.995:checks.append('4H turn up')
 if s['rs']>0:checks.append('BTC relative strength')
 if f is None or f<.05:checks.append('funding not overheated')
 n=len(checks)
 return('CONFIRMED' if n>=4 else'NEAR ENTRY'),n,checks
def action(c,s,e,ev,st):
 trend=100 if e.get('e20') and e.get('e50') and e.get('e200') and e['e20']>e['e50']>e['e200'] else 70;pull=95 if st=='CONFIRMED' else 85 if st in('NEAR ENTRY','EVENT HOLD') else 55;rs=max(0,min(100,50+s['rs']*2));event=max(0,min(100,50+ev['event_score']*8));v=.4*((trend+pull)/2)+.25*rs+.15*75+.15*event+.05*(70 if e.get('deriv') else 40)
 if st in('INVALIDATED','UNVERIFIED'):v=min(v,35)
 if st=='OVEREXTENDED':v=min(v,55)
 if st=='EVENT HOLD':v=min(v,65)
 return round(v)
def row(c,s,e,events,risk):
 base=classify(c,s,e);base,n,checks=confirm(c,s,e,base);st,ev=overlay(base,c['symbol'].upper(),events,risk);act=action(c,s,e,ev,st);return{'id':c['id'],'symbol':c['symbol'].upper(),'name':c['name'],'rank':c['market_cap_rank'],'price':c['current_price'],'tier':'CORE','quality':s['score'],'final':act,'action_score':act,'confidence':min(100,45+(35 if e.get('ok') else 0)+(15 if e.get('deriv') else 0)),'status':st,'base_status':ev['base_status'],'confirmation_score':n,'confirmation_checks':checks,'entry_signal':st=='CONFIRMED','event_risk':ev['event_risk'],'catalyst':ev['catalyst'],'event_score':ev['event_score'],'events':ev['events'],'data_source':e.get('source'),'d7':round(s['d7'],2),'d30':round(s['d30'],2),'rs':round(s['rs'],2),'funding':e.get('funding'),'e20':e.get('e20'),'e50':e.get('e50'),'rsi4h':e.get('rsi')}
def regime(coins):
 btc=next(x for x in coins if x['id']=='bitcoin');alts=[x for x in coins if x['market_cap_rank']>10 and not excluded(x)];br=sum((x.get('price_change_percentage_7d_in_currency') or 0)>0 for x in alts)/max(1,len(alts))*100;s=round(max(0,min(100,50+max(-15,min(15,(btc.get('price_change_percentage_30d_in_currency') or 0)*.45))+(br-50)*.18)));return{'score':s,'name':'RISK-ON' if s>=80 else'SELECTIVE RISK-ON' if s>=65 else'NEUTRAL' if s>=50 else'RISK-OFF','breadth':round(br,1)}
def update_perf(rows):
 p=load_json(PERF_PATH,{'version':'1.1','signals':[]});now=datetime.now(timezone.utc).isoformat();sig=p.setdefault('signals',[]);keys={(x.get('symbol'),x.get('opened_status')) for x in sig if not x.get('closed')}
 for r in rows:
  if r['status']=='CONFIRMED' and(r['symbol'],'CONFIRMED')not in keys:sig.append({'symbol':r['symbol'],'opened_at':now,'opened_status':'CONFIRMED','entry_price':r['price'],'action_score':r['action_score'],'confirmation_score':r['confirmation_score'],'event_score':r['event_score'],'rank':r['rank'],'closed':False})
  for x in sig:
   if x.get('symbol')==r['symbol'] and not x.get('closed'):
    ret=(r['price']/x['entry_price']-1)*100;x.update(last_price=r['price'],last_return_pct=round(ret,2),mfe_pct=round(max(x.get('mfe_pct',-999),ret),2),mae_pct=round(min(x.get('mae_pct',999),ret),2),last_status=r['status'],last_checked_at=now)
    if r['status'] in('INVALIDATED','OVEREXTENDED'):x.update(closed=True,closed_at=now,close_reason=r['status'])
 p['version']='1.1';p['updated_at']=now;PERF_PATH.write_text(json.dumps(p,ensure_ascii=False,indent=2))
def main():
 coins=universe()
 if not coins:raise SystemExit('market unavailable')
 cache=load_json(CACHE_PATH,{});risk,events=active_events();btc=next(x for x in coins if x['id']=='bitcoin');inv=[c for c in coins if not excluded(c)];core=inv[:25];sc={c['id']:score(c,btc) for c in inv};rows=[]
 for c in core:
  e=tech(c,cache);e.update(deriv(c));e['source']=e.get('source','coingecko')+('+binance' if e.get('deriv') else'+no-derivatives');rows.append(row(c,sc[c['id']],e,events,risk))
 opp=sorted([{'id':c['id'],'symbol':c['symbol'].upper(),'name':c['name'],'rank':c['market_cap_rank'],'price':c['current_price'],'tier':'OPPORTUNITY','quality':sc[c['id']]['score'],'status':'RADAR','d7':round(sc[c['id']]['d7'],2),'d30':round(sc[c['id']]['d30'],2),'rs':round(sc[c['id']]['rs'],2)} for c in inv[25:100]],key=lambda x:(x['quality'],x['rs']),reverse=True);prom=[x for x in opp if x['quality']>=62 and x['d30']>0 and x['rs']>2][:10];update_perf(rows);sp=DATA/'monitor_state.json';prev=load_json(sp,{}).get('states',{});states={r['id']:r['status'] for r in rows};alerts=[{'id':r['id'],'symbol':r['symbol'],'from':prev.get(r['id']),'to':r['status'],'price':r['price'],'final':r['final']}for r in rows if prev.get(r['id'])!=r['status'] and r['status'] in('CONFIRMED','EVENT HOLD','INVALIDATED')];res={'version':'4.2','updated_at':datetime.now(timezone.utc).isoformat(),'market_risk':risk,'active_event_count':len(events),'regime':regime(coins),'tiers':{'core_count':25,'opportunity_count':75,'discovery_count':len(inv[100:300])},'data_quality':{'core_verified':sum(r['status']!='UNVERIFIED' for r in rows),'core_unverified':sum(r['status']=='UNVERIFIED' for r in rows),'derivatives_verified':sum(r.get('funding')is not None for r in rows),'confirmed_count':sum(r['status']=='CONFIRMED' for r in rows),'cache_used':sum('cache'in(r.get('data_source')or'')for r in rows)},'core':rows,'opportunity':opp[:15],'promotions':prom,'alerts':alerts,'performance_tracking':{'enabled':True,'entry_basis':'CONFIRMED'}};CACHE_PATH.write_text(json.dumps(cache,ensure_ascii=False,indent=2));(DATA/'latest.json').write_text(json.dumps(res,ensure_ascii=False,indent=2));sp.write_text(json.dumps({'updated_at':res['updated_at'],'states':states},ensure_ascii=False,indent=2));(DATA/'alerts.json').write_text(json.dumps(alerts,ensure_ascii=False,indent=2))
 update_calibration(DATA,rows,res['regime'],res['updated_at'])
if __name__=='__main__':main()
