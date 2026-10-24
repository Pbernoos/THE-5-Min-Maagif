"""Read-only prospective Polymarket data collector. No orders or forecasts.

python collector.py collect --db data/market.sqlite3
python collector.py export --db data/market.sqlite3 --out export.jsonl
python collector.py features --db data/market.sqlite3 --window UNIX_START
"""
import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import zlib

SOURCE='https://data.chain.link/streams/btc-usd-twap-60s-streams'
TOPIC='crypto_prices_twap_sixty'
NS=1_000_000_000

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def slug(t):return f'btc-updown-5m-{t}'
def array(x):return json.loads(x) if isinstance(x,str) else x
def window(t):return int(t)//300*300
def number(x):
    if isinstance(x,bool):raise ValueError('Boolean is not numeric data')
    v=float(x)
    if not math.isfinite(v):raise ValueError('Non-finite number')
    return v

def market(data,t):
    from datetime import datetime
    if not isinstance(data,list):raise ValueError('Invalid market response')
    es=[e for e in data if e.get('slug')==slug(t)]
    if len(es)!=1:raise ValueError('Market unavailable')
    ms=[m for m in es[0].get('markets',[]) if m.get('slug')==slug(t)]
    if len(ms)!=1:raise ValueError('Nonunique market')
    m=ms[0];names=array(m['outcomes']);tokens=array(m['clobTokenIds'])
    if len(names)!=2 or set(names)!={'Up','Down'} or len(tokens)!=2:raise ValueError('Invalid token map')
    if any(not isinstance(x,str) or not x.isdigit() or len(x)>128 for x in tokens) or tokens[0]==tokens[1]:
        raise ValueError('Invalid token IDs')
    c=m.get('cryptoMarketConfig',{})
    if m.get('resolutionSource')!=SOURCE or c.get('asset')!='btc' or c.get('duration')!='5m' or c.get('twapEnabled') is not True or c.get('twapLookbackSeconds')!=60:
        raise ValueError('Wrong settlement feed/configuration')
    stamp=lambda s:datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
    if stamp(m['eventStartTime'])!=t or stamp(m['endDate'])!=t+300:raise ValueError('Wrong window times')
    if not isinstance(m.get('conditionId'),str) or not m['conditionId']:raise ValueError('Missing condition ID')
    return {'window':t,'condition_id':m['conditionId'],'tokens':dict(zip(names,tokens)),'raw':m}

def parse_book(raw,meta,side,received_ns):
    if str(raw.get('asset_id'))!=meta['tokens'][side] or raw.get('market')!=meta['condition_id']:
        raise ValueError('Book/market/token mismatch')
    ms=number(raw['timestamp']);source_ns=int(ms*1_000_000)
    if ms<=0 or ms!=int(ms) or source_ns>received_ns+2*NS:raise ValueError('Invalid/future book timestamp')
    levels={}
    for k in ['bids','asks']:
        if not isinstance(raw.get(k),list):raise ValueError('Missing book side')
        v=[]
        for x in raw[k]:
            p=number(x['price']);s=number(x['size'])
            if not 0<=p<=1 or s<0:raise ValueError('Invalid price or size')
            if s>0:v.append({'price':p,'size':s})
        levels[k]=sorted(v,key=lambda x:x['price'],reverse=k=='bids')[:20]
    if not levels['bids'] or not levels['asks']:raise ValueError('One-sided/empty book; quote unavailable')
    bid=levels['bids'][0]['price'];ask=levels['asks'][0]['price']
    if bid>ask:raise ValueError('Crossed book')
    b=sum(x['size'] for x in levels['bids']);a=sum(x['size'] for x in levels['asks'])
    return dict(source_ns=source_ns,side=side,token_id=meta['tokens'][side],condition_id=meta['condition_id'],
        bid=bid,ask=ask,midpoint=(bid+ask)/2,spread=ask-bid,depth_imbalance_20=(b-a)/(b+a),
        bid_depth_20=b,ask_depth_20=a,**levels)

def oracle_points(raw,received_ns):
    if raw.get('topic')!=TOPIC or raw.get('type') not in ['subscribe','update']:raise ValueError('Wrong oracle topic/type')
    p=raw.get('payload',{})
    if p.get('symbol')!='btc/usd' or p.get('window_s')!=60:raise ValueError('Wrong oracle symbol/window')
    rows=p.get('data') if raw['type']=='subscribe' else [p]
    if not isinstance(rows,list) or len(rows)>1200:raise ValueError('Invalid oracle rows')
    out=[]
    for r in rows:
        ms=r.get('timestamp');v=number(r['value'])
        if isinstance(ms,bool) or not isinstance(ms,int) or ms%1000 or ms<=0 or v<=0:raise ValueError('Invalid oracle point')
        t=ms*1_000_000
        if t>received_ns+2*NS or t<received_ns-600*NS:raise ValueError('Future/expired oracle point')
        full=r.get('full_accuracy_value')
        if full is not None and (not isinstance(full,str) or not full.isdigit() or len(full)>80):raise ValueError('Invalid exact value')
        out.append(dict(source_ns=t,price=v,full_accuracy_value=full))
    if not out:raise ValueError('Empty oracle snapshot')
    return out

def official_outcome(meta,now_ns):
    m=meta['raw'];t=meta['window']
    if now_ns<(t+300)*NS or m.get('closed') is not True or m.get('umaResolutionStatus')!='resolved':return None
    raw=array(m['outcomePrices'])
    if not isinstance(raw,list) or len(raw)!=2:return None
    prices=dict(zip(array(m['outcomes']),[number(x) for x in raw]))
    if set(prices)!={'Up','Down'} or sorted(prices.values())!=[0.,1.]:return None
    return int(prices['Up'])

class Store:
    def __init__(self,path,max_bytes=1024**3):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.max_bytes=max_bytes
        self.c=sqlite3.connect(self.path);self.c.row_factory=sqlite3.Row
        tables={r[0] for r in self.c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        expected={'records','markets','outcomes'}
        if tables and (self.c.execute('PRAGMA user_version').fetchone()[0]!=1 or tables!=expected or {r[1] for r in self.c.execute('PRAGMA table_info(records)')}!=
            {'id','kind','window_ts','source_ns','received_ns','stored_ns','valid','sha256','payload'}):
            self.c.close();raise ValueError('Not a collector database; choose a NEW path, existing database left unchanged')
        self.c.execute('PRAGMA journal_mode=WAL');self.c.execute('PRAGMA synchronous=FULL')
        self.c.executescript('''CREATE TABLE IF NOT EXISTS records(
          id INTEGER PRIMARY KEY,kind TEXT NOT NULL,window_ts INTEGER,source_ns INTEGER,
          received_ns INTEGER NOT NULL,stored_ns INTEGER NOT NULL,valid INTEGER NOT NULL,
          sha256 TEXT NOT NULL,payload BLOB NOT NULL);
          CREATE INDEX IF NOT EXISTS records_asof ON records(kind,window_ts,received_ns);
          CREATE TABLE IF NOT EXISTS markets(window_ts INTEGER PRIMARY KEY,next_check REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS outcomes(window_ts INTEGER PRIMARY KEY,up INTEGER NOT NULL,record_id INTEGER NOT NULL);
          PRAGMA user_version=1;''');self.c.commit()
    def close(self):self.c.close()
    def size(self):return sum(p.stat().st_size for p in [self.path,Path(str(self.path)+'-wal'),Path(str(self.path)+'-shm')] if p.exists())
    def add(self,kind,t,payload,received_ns=None,source_ns=None,valid=True):
        received_ns=received_ns or time.time_ns();stored_ns=time.time_ns()
        if received_ns>stored_ns or self.size()>=self.max_bytes:raise RuntimeError('Clock/storage failure; capture stopped, no records deleted')
        raw=canonical(payload).encode()
        if len(raw)>2_000_000:raise ValueError('Oversized record')
        with self.c:
            cur=self.c.execute('INSERT INTO records VALUES(NULL,?,?,?,?,?,?,?,?)',
                (kind,t,source_ns,received_ns,0,int(valid),hashlib.sha256(raw).hexdigest(),zlib.compress(raw)))
        # Timestamp AFTER the payload's durable commit. A crash before the second
        # commit leaves stored_ns=0 so the record cannot become a training feature.
        committed_ns=time.time_ns()
        if committed_ns<received_ns:raise RuntimeError('Clock moved backwards; capture stopped')
        with self.c:self.c.execute('UPDATE records SET stored_ns=? WHERE id=?',(committed_ns,cur.lastrowid))
        return cur.lastrowid
    def remember(self,t):
        with self.c:self.c.execute('INSERT OR IGNORE INTO markets VALUES(?,?)',(t,t+360))
    def pending(self,now):
        return [r[0] for r in self.c.execute('''SELECT m.window_ts FROM markets m LEFT JOIN outcomes o USING(window_ts)
            WHERE o.window_ts IS NULL AND m.next_check<=? AND m.window_ts+300<=? ORDER BY m.next_check LIMIT 4''',(now,now))]
    def defer(self,t,now):
        with self.c:self.c.execute('UPDATE markets SET next_check=? WHERE window_ts=?',(now+300,t))
    def outcome(self,meta,received_ns):
        t=meta['window'];up=official_outcome(meta,received_ns)
        if up is not None:
            old=self.c.execute('SELECT up FROM outcomes WHERE window_ts=?',(t,)).fetchone()
            if old is not None:
                if old[0]!=up:raise RuntimeError('Conflicting outcome; original label preserved')
                return
            i=self.add('official_outcome',t,{'up':up,'market':meta},received_ns)
            with self.c:self.c.execute('INSERT INTO outcomes VALUES(?,?,?)',(t,up,i))
        else:
            with self.c:self.c.execute('UPDATE markets SET next_check=? WHERE window_ts=?',(received_ns/NS+300,t))
    def unpack(self,row):
        d=dict(row);raw=zlib.decompress(d.pop('payload'))
        if hashlib.sha256(raw).hexdigest()!=d['sha256']:raise RuntimeError('Payload integrity mismatch')
        d['payload']=json.loads(raw);return d
    def stats(self):
        return dict(records={r[0]:r[1] for r in self.c.execute('SELECT kind,count(*) FROM records GROUP BY kind')},
            labels=self.c.execute('SELECT count(*) FROM outcomes').fetchone()[0],bytes=self.size())
    def asof(self,t,cutoff_ns):
        if isinstance(t,bool) or not isinstance(t,int) or t<=0 or t%300 or cutoff_ns>=t*NS:
            raise ValueError('Features require a positive window and explicit PRE-start cutoff')
        def recent(kind,market_ts):
            return [self.unpack(r) for r in self.c.execute('''SELECT * FROM records WHERE kind=? AND valid=1
                AND (window_ts=? OR ? IS NULL) AND received_ns<=? AND stored_ns>0 AND stored_ns<=?
                ORDER BY id DESC LIMIT 80''',(kind,market_ts,market_ts,cutoff_ns,cutoff_ns))]
        books={}
        for row in recent('book',t):
            b=row['payload']['normalized'];source=b['source_ns']
            if 0<=cutoff_ns-source<=10*NS and 0<=cutoff_ns-row['received_ns']<=10*NS:
                books.setdefault(b['side'],dict(record_id=row['id'],**b))
        points=[]
        for row in recent('oracle',None):
            for p in row['payload']['points']:
                if 0<=cutoff_ns-p['source_ns']<=10*NS and 0<=cutoff_ns-row['received_ns']<=10*NS:
                    points.append(dict(record_id=row['id'],**p))
        latest=max(points,key=lambda p:p['source_ns']) if points else None
        return dict(window=t,cutoff_ns=cutoff_ns,books=books,oracle=latest,
            complete=set(books)=={'Up','Down'} and latest is not None,
            note='Incomplete rows are missing data, never zero-filled; opening/closing oracle values after cutoff are excluded.')

class Collector:
    def __init__(self,store,interval=5):self.store=store;self.interval=interval;self.cache={}
    def error(self,source,error,t=None):
        self.store.add('health',t,dict(source=source,status='unavailable',error=str(error)[:400]),valid=False)
    async def get(self,s,url,params):
        import aiohttp
        for attempt in range(2):
            try:
                async with s.get(url,params=params) as r:
                    if r.status in [401,403]:raise PermissionError('Public feed denied access; collector stopped, no bypass attempted')
                    if r.status>=500 and not attempt:await asyncio.sleep(1);continue
                    r.raise_for_status();data=await r.json();received=time.time_ns()
                    return data,received
            except (aiohttp.ClientConnectionError,asyncio.TimeoutError):
                if attempt:raise
                await asyncio.sleep(1)
        raise RuntimeError('Public API unavailable')
    async def discover(self,s,t,refresh=False):
        if not refresh and t in self.cache:return self.cache[t]
        raw,received=await self.get(s,'https://gamma-api.polymarket.com/events',{'slug':slug(t)})
        meta=market(raw,t)
        self.store.add('market',t,dict(raw=raw,normalized=meta),received)
        self.store.remember(t)
        if not refresh:self.cache[t]=meta
        self.cache={k:v for k,v in self.cache.items() if k>=window(time.time())-300}
        return meta
    async def books(self,s,t):
        import aiohttp
        meta=await self.discover(s,t)
        async def one(side):
            try:
                raw,received=await self.get(s,'https://clob.polymarket.com/book',{'token_id':meta['tokens'][side]})
                try:
                    b=parse_book(raw,meta,side,received)
                except (ValueError,KeyError,TypeError) as e:
                    self.store.add('book_rejected',t,dict(raw=raw,error=str(e)),received,valid=False);return
                self.store.add('book',t,dict(raw=raw,normalized=b),received,b['source_ns'])
            except (aiohttp.ClientError,asyncio.TimeoutError,ValueError,KeyError,TypeError) as e:self.error('book/'+side,e,t)
        await asyncio.gather(one('Up'),one('Down'))
    async def poll(self,s):
        import aiohttp
        last_labels=0.
        while True:
            started=time.monotonic();now=time.time();ts=window(now)
            for t in [ts,ts+300]:
                try:await self.books(s,t)
                except (aiohttp.ClientError,asyncio.TimeoutError,ValueError,KeyError,TypeError) as e:self.error('market/books',e,t)
            if now-last_labels>=60:
                for t in self.store.pending(now):
                    try:
                        m=await self.discover(s,t,True);self.store.outcome(m,time.time_ns())
                    except (aiohttp.ClientError,asyncio.TimeoutError,ValueError,KeyError,TypeError) as e:
                        self.error('official-label',e,t);self.store.defer(t,time.time())
                last_labels=now
            print(canonical(dict(time=time.time(),**self.store.stats())),flush=True)
            await asyncio.sleep(max(.1,self.interval-(time.monotonic()-started)))
    async def oracle(self,s):
        import aiohttp
        attempt=0
        subscription=dict(action='subscribe',subscriptions=[dict(topic=TOPIC,type='update',filters=json.dumps({'symbol':'btc/usd'}))])
        while True:
            try:
                async with s.ws_connect('wss://ws-live-data.polymarket.com/',origin='https://polymarket.com',heartbeat=5,max_msg_size=2_000_000) as ws:
                    attempt=0;last=0.
                    self.store.add('health',None,dict(source='oracle',status='connected'))
                    while True:
                        if time.monotonic()-last>=10:
                            await ws.send_json(subscription);last=time.monotonic()
                        try:m=await ws.receive(timeout=2)
                        except asyncio.TimeoutError:continue
                        if m.type in [aiohttp.WSMsgType.CLOSE,aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR]:raise ConnectionError('Oracle connection closed')
                        if m.type!=aiohttp.WSMsgType.TEXT or m.data in ['PONG','PING','']:continue
                        received=time.time_ns()
                        try:
                            raw=json.loads(m.data)
                            if not isinstance(raw,dict) or raw.get('topic')!=TOPIC:continue
                            points=oracle_points(raw,received)
                            self.store.add('oracle',None,dict(raw=raw,points=points,snapshot=raw['type']=='subscribe'),received,max(p['source_ns'] for p in points))
                        except (ValueError,KeyError,TypeError) as e:
                            self.store.add('oracle_rejected',None,dict(raw_text=m.data,error=str(e)),received,valid=False)
            except (aiohttp.ClientError,asyncio.TimeoutError,ConnectionError) as e:
                if isinstance(e,aiohttp.WSServerHandshakeError) and e.status in [401,403]:
                    raise PermissionError('Oracle denied access; collector stopped, no bypass attempted') from e
                self.error('oracle',e);attempt+=1
                await asyncio.sleep(min(30,2**min(attempt,5)))
    async def run(self,seconds=0):
        import aiohttp
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as s:
            tasks=[asyncio.create_task(self.poll(s)),asyncio.create_task(self.oracle(s))]
            timer=asyncio.create_task(asyncio.sleep(seconds)) if seconds else None
            try:
                done,_=await asyncio.wait(tasks+([timer] if timer else []),return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task is not timer:task.result()
            finally:
                for task in tasks+([timer] if timer else []):task.cancel()
                await asyncio.gather(*tasks,*([timer] if timer else []),return_exceptions=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['collect','export','features','status'])
    p.add_argument('--db',default='data/market.sqlite3');p.add_argument('--max-mb',type=int,default=1024)
    p.add_argument('--seconds',type=int,default=0);p.add_argument('--interval',type=float,default=5)
    p.add_argument('--out');p.add_argument('--window',type=int);p.add_argument('--lead',type=int,default=15)
    a=p.parse_args()
    if a.max_mb<1 or a.seconds<0 or a.interval<2 or not 1<=a.lead<=299:p.error('Invalid capacity/timing bounds')
    if a.command!='collect' and not Path(a.db).is_file():p.error('Database not found; collect first')
    store=Store(a.db,a.max_mb*1024**2)
    try:
        if a.command=='collect':
            try:asyncio.run(Collector(store,a.interval).run(a.seconds))
            except KeyboardInterrupt:print('Stopped; collected records preserved.',flush=True)
        elif a.command=='features':
            if a.window is None:p.error('--window is required')
            print(canonical(store.asof(a.window,(a.window-a.lead)*NS)))
        elif a.command=='export':
            if not a.out:p.error('--out is required')
            out=Path(a.out);watermark=store.c.execute('SELECT coalesce(max(id),0) FROM records').fetchone()[0]
            with out.open('x',encoding='utf-8') as f:
                f.write(canonical(dict(schema=1,type='manifest',exported_ns=time.time_ns(),max_record_id=watermark,source=SOURCE))+'\n')
                for row in store.c.execute('SELECT * FROM records WHERE id<=? ORDER BY id',(watermark,)):
                    f.write(canonical(store.unpack(row))+'\n')
            print(canonical(dict(export=str(out),max_record_id=watermark)))
        else:print(canonical(store.stats()))
    finally:store.close()

if __name__=='__main__':main()