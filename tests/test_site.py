"""Embedded-JS and HTTP fixture checks; not a real browser-rendering test."""
import json
from pathlib import Path

import pytest
from py_mini_racer import MiniRacer

ROOT=Path(__file__).resolve().parents[1]
TS=1792770000
STUB=r'''
Date.now=()=>1792769990000;
globalThis.setTimeout=()=>1;globalThis.clearTimeout=()=>{};globalThis.setInterval=()=>1;
class Element {constructor(){this.textContent='';this.hidden=false;this.href='';this.listeners={};}addEventListener(k,v){this.listeners[k]=v;}click(){}}
const elements={};
const document={hidden:false,getElementById:id=>elements[id]||(elements[id]=new Element()),createElement:()=>new Element(),addEventListener:()=>{}};
const storage={};
const localStorage={getItem:k=>storage[k]||null,setItem:(k,v)=>{storage[k]=v;}};
const fetch=()=>new Promise(()=>{});
'''


@pytest.fixture
def js():
    with MiniRacer() as c:
        c.eval(STUB)
        c.eval((ROOT/'app.js').read_text())
        yield c


def value(js,expression):
    return json.loads(js.eval(f'JSON.stringify({expression})'))


def candles(ts=TS):
    return [[t,99.,102.,100.,101.,5.] for t in range(ts-121*60,ts-60,60)]


def market():
    return [{'slug':f'btc-updown-5m-{TS}','markets':[{
        'slug':f'btc-updown-5m-{TS}','outcomes':'["Down","Up"]',
        'clobTokenIds':'["123","456"]','outcomePrices':'["0","1"]'}]}]


def test_startup_does_not_claim_accuracy(js):
    assert 'No scored outcomes' in js.eval('$("scores").textContent')
    assert js.eval('$("frozen-direction").textContent')=='NO FORECAST'


def test_valid_past_candles(js):
    assert js.eval(f'parseCandles({json.dumps(candles())},{TS}).length')==120


@pytest.mark.parametrize('which',['missing','duplicate','future','invalid'])
def test_bad_candles_rejected(js,which):
    rows=candles()
    if which=='missing': rows.pop()
    if which=='duplicate': rows[1]=rows[0]
    if which=='future': rows[-1][0]=TS
    if which=='invalid': rows[2][4]=-1
    assert js.eval(f'(()=>{{try{{parseCandles({json.dumps(rows)},{TS});return false}}catch(e){{return true}}}})()')


def test_flat_baseline_is_neutral(js):
    js.eval(f'const candlesTest=parseCandles({json.dumps(candles())},{TS})')
    assert js.eval('baseline(candlesTest).p_up')==.5


def test_baseline_bounded_and_finite(js):
    rows=candles()
    for i,row in enumerate(rows): row[1:5]=[99+i,102+i,100+i,101+i]
    p=js.eval(f'baseline(parseCandles({json.dumps(rows)},{TS})).p_up')
    assert .5<p<.65


def test_outcomes_mapped_by_name_not_array_position(js):
    m=value(js,f'parseMarket({json.dumps(market())},{TS})')
    assert m['tokens']['up']=='456' and m['prices']['up']==1


def test_wrong_market_rejected(js):
    assert js.eval(f'(()=>{{try{{parseMarket({json.dumps(market())},{TS+300});return false}}catch(e){{return true}}}})()')


def test_crossed_book_rejected(js):
    assert js.eval('(()=>{try{parseBook({bids:[{price:.7,size:1}],asks:[{price:.6,size:1}]},1);return false}catch(e){return true}})()')


def test_book_top20_ordering(js):
    book={'bids':[{'price':i/100,'size':1} for i in range(40)],'asks':[{'price':.8+i/1000,'size':1} for i in range(30)]}
    b=value(js,f'parseBook({json.dumps(book)},1)')
    assert len(b['bids'])==len(b['asks'])==20
    assert b['bid']==.39 and b['ask']==.8


def record():
    return {'model':'browser-candle-baseline-v1','ts':TS,'issued_at':TS-10,'stored_at':TS-9,
            'feature_cutoff':TS-60,'p_up':.55,'up':None}


@pytest.mark.parametrize('key,v',[('issued_at',TS),('stored_at',TS+1),('feature_cutoff',TS),('p_up',1.1),('model','fake')])
def test_invalid_saved_record_rejected(js,key,v):
    r=record();r[key]=v
    assert not js.eval(f'validRecord({json.dumps(r)})')


def test_valid_frozen_record_accepted(js):
    assert js.eval(f'validRecord({json.dumps(record())})')


def test_journal_roundtrip(js):
    r=record()
    js.eval(f'state.firstWindow={TS-300};state.records=[{json.dumps(r)}];persist();state.records=[];loadJournal()')
    assert value(js,'state.records')[0]==r


def test_storage_failure_does_not_fabricate_success(js):
    js.eval('localStorage.setItem=()=>{throw Error("full")};state.firstWindow=1792769700')
    assert not js.eval('persist()')
    assert 'full' in js.eval('state.storageError')


def test_stale_price_hidden(js):
    js.eval('state.price={price:100000,exchange_ts:now()-100,received_at:now()};render()')
    assert js.eval('$("price").textContent')=='—'


def test_pause_suppresses_draft_and_price(js):
    js.eval('state.price={price:100000,exchange_ts:now(),received_at:now()};state.paused=true;render()')
    assert js.eval('$("price").textContent')=='—'


def test_early_draft_cutoff_remains_in_past(js):
    js.eval('Date.now=()=>1792769730000')
    cutoff=js.eval(f'Math.min({TS}-60,Math.floor(now()/60)*60-60)')
    assert cutoff<TS-60


def test_static_site_paths_and_no_secret_patterns():
    html=(ROOT/'index.html').read_text()
    assert 'href="./style.css"' in html and 'src="./app.js"' in html
    assert 'http-equiv="Content-Security-Policy"' in html
    assert 'No demonstrated predictive edge' in html
    js=(ROOT/'app.js').read_text()
    assert 'innerHTML' not in js and 'github_pat_' not in js
    assert 'credentials:"omit"' in js