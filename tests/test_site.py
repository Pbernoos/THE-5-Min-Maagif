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
class Element {
 constructor(){this.textContent='';this.hidden=false;this.href='';this.listeners={};this.attrs={};this.children=[];this.classList={toggle:()=>{}};}
 addEventListener(k,v){this.listeners[k]=v;}click(){}
 setAttribute(k,v){this.attrs[k]=String(v);}getAttribute(k){return this.attrs[k]??null;}
 appendChild(c){this.children.push(c);return c;}replaceChildren(...c){this.children=c;}
}
const elements={};
const rangeButtons=[15,60,120].map(n=>{const e=new Element();e.setAttribute('data-range',n);return e;});
const document={hidden:false,getElementById:id=>elements[id]||(elements[id]=new Element()),createElement:()=>new Element(),addEventListener:()=>{},querySelectorAll:s=>s==='[data-range]'?rangeButtons:[]};
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
    assert 'href="./style.css?v=3"' in html and 'src="./app.js?v=3"' in html
    assert 'href="./terminal.css?v=3"' in html
    assert 'http-equiv="Content-Security-Policy"' in html
    assert 'No demonstrated predictive edge' in html
    js=(ROOT/'app.js').read_text()
    assert 'innerHTML' not in js and 'github_pat_' not in js
    assert 'credentials:"omit"' in js


def test_chart_has_no_synthetic_startup_points(js):
    assert js.eval('$("price-path").getAttribute("d")')==''
    assert not js.eval('$("chart-empty").hidden')


def test_chart_flat_prices_have_finite_geometry(js):
    rows=[{'ts':TS-60*i,'close':100} for i in range(60,0,-1)]
    g=value(js,f'chartGeometry({json.dumps(rows)},60)')
    assert g['change']==0 and g['low']<100<g['high']
    assert 'NaN' not in g['line'] and 'Infinity' not in g['line']


@pytest.mark.parametrize('count',[15,60,120])
def test_chart_range_uses_real_available_rows(js,count):
    rows=[{'ts':TS-60*(120-i),'close':100+i} for i in range(120)]
    g=value(js,f'chartGeometry({json.dumps(rows)},{count})')
    assert g['count']==count and g['close']==219
    assert g['last']==TS


def test_chart_change_is_candle_range_not_fabricated_window_return(js):
    assert js.eval('chartGeometry([{ts:1,close:100},{ts:61,close:110}],60).change')==pytest.approx(.1)


def test_chart_empty_or_invalid_data_rejected(js):
    assert js.eval('chartGeometry([],60)') is None
    assert js.eval('chartGeometry([{ts:1,close:100},{ts:61,close:-1}],60)') is None


def test_stale_chart_is_suppressed(js):
    js.eval('state.chart={received_at:now()-151,candles:[{ts:1,close:100},{ts:61,close:110}]};renderChart()')
    assert js.eval('$("price-path").getAttribute("d")')==''
    assert js.eval('$("chart-close").textContent')=='—'


def test_range_buttons_change_accessible_selection(js):
    js.eval('rangeButtons[0].listeners.click()')
    assert js.eval('state.chartRange')==15
    assert js.eval('rangeButtons[0].getAttribute("aria-pressed")')=='true'
    assert js.eval('rangeButtons[1].getAttribute("aria-pressed")')=='false'


def test_new_journal_is_empty_not_demo_results(js):
    assert js.eval('$("journal-rows").children.length')==0
    assert not js.eval('$("journal-empty").hidden')


def test_journal_renders_saved_prestart_record_without_promoting_pending_label(js):
    js.eval(f'state.records=[{json.dumps(record())}];renderJournal()')
    assert js.eval('$("journal-rows").children.length')==1
    assert js.eval('$("journal-rows").children[0].children[4].textContent')=='Not started'


def test_display_limit_does_not_remove_saved_records(js):
    records=[]
    for i in range(12):
        r=record();r.update(ts=TS-i*300,issued_at=TS-i*300-10,stored_at=TS-i*300-9)
        records.append(r)
    js.eval(f'state.records={json.dumps(records)};renderJournal()')
    assert js.eval('$("journal-rows").children.length')==10
    assert js.eval('state.records.length')==12


def test_midpoint_cards_hidden_when_book_is_stale(js):
    js.eval('state.books={ts:windowAt(now()),up:{bid:.4,ask:.6,received_at:now()-30,exchange_ts:null}};render()')
    assert js.eval('$("up-mid").textContent')=='—'
    assert js.eval('$("up-meter").hidden')


def test_midpoint_cards_are_quotes_not_model_predictions(js):
    js.eval('state.books={ts:windowAt(now()),up:{bid:.4,ask:.6,received_at:now(),exchange_ts:null}};render()')
    assert js.eval('$("up-mid").textContent')=='50.0%'
    assert not js.eval('$("up-meter").hidden')


def test_html_has_unique_ids_and_all_literal_js_targets():
    import re
    html=(ROOT/'index.html').read_text()
    ids=re.findall(r'\bid="([^"]+)"',html)
    assert len(ids)==len(set(ids))
    source=(ROOT/'app.js').read_text()
    targets=set(re.findall(r'(?:\$|text)\("([a-z][a-z-]+)"',source))
    assert targets<=set(ids)
    assert '<svg' in html and '<table' in html and 'aria-pressed' in html


@pytest.mark.parametrize('stamp,expected',[
    ('2026-10-23T17:57:22Z','21:27'),
    ('2026-06-23T17:57:22Z','21:27'),
    ('2026-10-23T21:00:00Z','00:30'),
])
def test_tehran_time_uses_iana_zone_not_device_zone(js,stamp,expected):
    assert js.eval(f'localTime(Date.parse("{stamp}")/1000)')==expected


def test_tehran_date_rollover(js):
    assert js.eval('localDate(Date.parse("2026-10-23T21:00:00Z")/1000)')=='2026-10-24'


def test_timezone_does_not_shift_real_market_boundaries(js):
    ts=js.eval('windowAt(Date.parse("2026-10-23T17:57:22Z")/1000)')
    assert js.eval(f'new Date({ts}*1000).toISOString()')=='2026-10-23T17:55:00.000Z'
    assert js.eval(f'localTime({ts})')=='21:25'


def test_forecast_target_is_next_complete_window_in_tehran(js):
    js.eval('Date.now=()=>Date.parse("2026-10-23T17:57:22Z");render()')
    label=js.eval('$("target").textContent')
    assert '21:30–21:35 Tehran' in label and 'not a rolling five minutes' in label


def test_journal_dates_also_use_tehran(js):
    js.eval(f'state.records=[{json.dumps(record())}];renderJournal()')
    assert js.eval('$("journal-rows").children[0].children[0].textContent')=='2026-10-23 19:10'


def test_paired_market_comparison_excludes_missing_quotes(js):
    r=record();r['up']=1
    assert js.eval(f'pairedMarketScores([{json.dumps(r)}])') is None


def paired_record():
    r=record();r.update(up=1,market_p_up=.5,context={'books':{'up':{
        'bid':.4,'ask':.6,'received_at':TS-11,'exchange_ts':TS-12}}})
    return r


def test_paired_brier_uses_identical_valid_cohort(js):
    r=paired_record()
    score=value(js,f'pairedMarketScores([{json.dumps(r)}])')
    assert score['n']==1 and score['market']==.25
    assert score['model']==pytest.approx((.55-1)**2)


@pytest.mark.parametrize('field,v',[('exchange_ts',TS-100),('received_at',TS-5),('exchange_ts',None)])
def test_paired_comparison_rejects_stale_future_or_untimestamped_quotes(js,field,v):
    r=paired_record();r['context']['books']['up'][field]=v
    assert js.eval(f'pairedMarketScores([{json.dumps(r)}])') is None