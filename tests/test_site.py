"""Embedded-JS and HTTP fixture checks; not a real browser-rendering test."""
import json
from pathlib import Path

import pytest
from py_mini_racer import MiniRacer

ROOT=Path(__file__).resolve().parents[1]
TS=1792770000
STUB=r'''
Date.now=()=>1792769990000;
globalThis.setTimeout=()=>1;globalThis.clearTimeout=()=>{};globalThis.setInterval=()=>1;globalThis.clearInterval=()=>{};
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
    assert 'href="./style.css?v=6"' in html and 'src="./app.js?v=6"' in html
    assert 'href="./terminal.css?v=6"' in html
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


def oracle_message(ts=TS-300,price=81531.15249742479):
    return {'topic':'crypto_prices_twap_sixty','type':'subscribe',
            'payload':{'symbol':'btc/usd','window_s':60,'data':[{'timestamp':ts*1000,'value':price}]}}


def oracle_state(js,price=101,reference=100,source='polymarket-twap-boundary'):
    matching_oracle_market(js)
    js.eval(f'Date.now=()=>{TS+30}000;state.oracle.socket={{readyState:1}};state.oracle.reference={{ts:{TS},price:{reference},source:"{source}",captured_at:{TS+1}}};state.oracle.latest={{price:{price},exchange_ts:now()-2,received_at:now()}}')


def matching_oracle_market(js):
    js.eval(f'state.lastCurrent={{ts:{TS},source:ORACLE,raw:{{slug:slug({TS}),eventStartTime:new Date({TS}000).toISOString(),endDate:new Date({TS+300}000).toISOString(),cryptoMarketConfig:{{asset:"btc",duration:"5m",twapEnabled:true,twapLookbackSeconds:60}}}}}}')


@pytest.mark.parametrize('price,side',[(101,'up'),(99,'down'),(100,'up')])
def test_price_to_beat_direction_and_exact_tie_rule(js,price,side):
    oracle_state(js,price)
    assert js.eval('oracleComparison().direction')==side
    assert js.eval('oracleComparison().delta')==price-100


@pytest.mark.parametrize('price',[100,100.002,99.998])
def test_rounded_manual_tie_not_given_false_precision(js,price):
    oracle_state(js,price,source='manual')
    assert js.eval('oracleComparison().direction')=='rounded-tie'


def test_price_to_beat_is_not_coinbase_proxy(js):
    oracle_state(js,99)
    js.eval('state.price={price:100000,exchange_ts:now(),received_at:now()};render()')
    assert js.eval('$("reference-direction").textContent')=='DOWN'
    assert js.eval('oracleComparison().delta')==-1


@pytest.mark.parametrize('code',[
    'state.oracle.latest.exchange_ts=now()-21',
    'state.oracle.latest.received_at=now()-21',
    'state.oracle.latest.exchange_ts=now()+3',
    f'state.oracle.latest.exchange_ts={TS-1}',
    f'state.oracle.reference.ts={TS-300}',
    'state.oracle.socket.readyState=3',
    'state.paused=true',
    'state.oracle.reference=null',
    'state.oracle.latest=null',
])
def test_comparison_suppressed_when_reference_or_live_price_not_valid(js,code):
    oracle_state(js)
    js.eval(code+';renderOracle()')
    expected='REFERENCE NEEDED' if code in ['state.oracle.reference=null',f'state.oracle.reference.ts={TS-300}'] else 'WAITING'
    assert js.eval('$("reference-direction").textContent')==expected
    assert js.eval('oracleComparison().direction') is None


def test_comparison_resets_at_each_five_minute_boundary(js):
    oracle_state(js)
    js.eval('renderOracle();$("reference-input").value="100";Date.now=()=>'+str((TS+300)*1000)+';renderOracle()')
    assert js.eval('$("reference-direction").textContent')=='WAITING'
    assert js.eval('$("price-to-beat").textContent')=='—'
    assert js.eval('$("reference-input").value')==''


def test_exact_boundary_feed_point_sets_automatic_reference(js):
    js.eval(f'Date.now=()=>{TS+10}000')
    m=oracle_message(TS)
    assert js.eval(f'ingestOracleMessage({json.dumps(m)})')
    assert js.eval('state.oracle.reference.price')==m['payload']['data'][0]['value']
    assert js.eval('state.oracle.reference.source')=='polymarket-twap-boundary'


def test_near_boundary_is_not_used_as_official_open(js):
    js.eval(f'Date.now=()=>{TS+10}000')
    assert js.eval(f'ingestOracleMessage({json.dumps(oracle_message(TS+1))})')
    assert js.eval('state.oracle.reference') is None


@pytest.mark.parametrize('field,bad',[
    ('topic','crypto_prices_chainlink'),('topic','crypto_prices'),('type','unknown'),
    ('symbol','eth/usd'),('window_s',30),('window_s',None),('window_s','60')])
def test_wrong_feed_symbol_or_lookback_rejected(js,field,bad):
    m=oracle_message()
    if field in ['topic','type']:m[field]=bad
    else:m['payload'][field]=bad
    assert value(js,f'parseOracleMessage({json.dumps(m)})')==[]


@pytest.mark.parametrize('point',[
    {'timestamp':TS*1000,'value':None},{'timestamp':TS*1000,'value':-1},
    {'timestamp':TS*1000,'value':'100'}, {'timestamp':(TS-1000)*1000,'value':100},
    {'timestamp':TS,'value':100}, {'timestamp':(TS+100)*1000,'value':100}])
def test_invalid_or_future_oracle_points_rejected(js,point):
    m=oracle_message();m['payload']['data']=[point]
    assert value(js,f'parseOracleMessage({json.dumps(m)})')==[]


def test_tick_update_and_snapshot_use_same_parser(js):
    m=oracle_message();p=m['payload'].pop('data')[0];m['payload'].update(p);m['type']='update'
    assert len(value(js,f'parseOracleMessage({json.dumps(m)})'))==1


@pytest.mark.parametrize('raw,expected',[('81,500.25',81500.25),('$81,500.25',81500.25),
    ('81500.25',81500.25),('0',None),('-1',None),('50%',None),('1e5',None),
    ('81,50',None),('<script>',None),('Infinity',None),('',None)])
def test_manual_price_input_is_numeric_not_html_or_odds(js,raw,expected):
    assert js.eval(f'parseReferenceInput({json.dumps(raw)})')==expected


def test_manual_reference_bound_to_window_and_persists_separately(js):
    js.eval(f'Date.now=()=>{TS+30}000')
    before=js.eval('localStorage.getItem(KEY)')
    assert js.eval(f'setManualReference("81,500.25",{TS})')
    assert js.eval('state.oracle.reference.source')=='manual'
    assert js.eval('localStorage.getItem(KEY)')==before
    js.eval('state.oracle.reference=null;loadReference()')
    assert js.eval('state.oracle.reference.price')==81500.25


def test_manual_input_boundary_race_rejected(js):
    js.eval(f'Date.now=()=>{TS+300}000')
    assert not js.eval(f'setManualReference("100",{TS})')
    assert js.eval('state.oracle.reference') is None


def test_manual_price_cannot_override_exact_automatic_value(js):
    oracle_state(js)
    assert not js.eval(f'setManualReference("500",{TS})')
    assert js.eval('state.oracle.reference.price')==100


def test_automatic_reference_reconciles_incorrect_manual_input(js):
    js.eval(f'Date.now=()=>{TS+10}000;setManualReference("1",{TS})')
    js.eval(f'ingestOracleMessage({json.dumps(oracle_message(TS,100))})')
    assert js.eval('state.oracle.reference.price')==100
    assert 'differs' in js.eval('state.oracle.notice')


def test_reference_storage_failure_keeps_live_display_without_changing_journal(js):
    js.eval(f'Date.now=()=>{TS+10}000;localStorage.setItem=()=>{{throw Error("full")}}')
    assert js.eval(f'setManualReference("100",{TS})')
    assert js.eval('state.oracle.reference.price')==100
    assert js.eval('state.storageError') is None


def test_subscription_has_exact_verified_twap_topic(js):
    data=json.loads(js.eval('oracleSubscription()'))
    assert data['subscriptions'][0]=={'topic':'crypto_prices_twap_sixty','type':'update','filters':'{"symbol":"btc/usd"}'}


def test_reference_is_not_a_forecast_or_official_label(js):
    oracle_state(js)
    js.eval('render()')
    assert 'NOT a prediction or an official result' in js.eval('$("reference-detail").textContent')
    assert js.eval('state.records.length')==0
    assert 'No scored outcomes' in js.eval('$("scores").textContent')


def test_csp_allows_only_needed_oracle_connection():
    html=(ROOT/'index.html').read_text()
    assert 'wss://ws-live-data.polymarket.com' in html
    assert 'LIVE POSITION · NOT A FORECAST' in html
    assert 'type="password"' not in html


WS_STUB=r'''
globalThis.intervalCalls=[];
globalThis.timeoutCalls=[];
globalThis.setInterval=f=>{intervalCalls.push(f);return intervalCalls.length;};
globalThis.setTimeout=f=>{timeoutCalls.push(f);return timeoutCalls.length;};
globalThis.sockets=[];
globalThis.WebSocket=class {
 constructor(url){this.url=url;this.readyState=0;this.sent=[];sockets.push(this);}
 send(s){this.sent.push(s);}
 close(){this.readyState=3;}
};
'''


def test_websocket_connect_subscribe_and_periodic_snapshot_refresh(js):
    js.eval(WS_STUB)
    js.eval('startOracle();sockets[0].readyState=1;sockets[0].onopen()')
    assert js.eval('sockets[0].url')=='wss://ws-live-data.polymarket.com'
    assert json.loads(js.eval('sockets[0].sent[0]'))['action']=='subscribe'
    js.eval('intervalCalls[0]();intervalCalls[0]()')
    sent=value(js,'sockets[0].sent')
    assert sent[1:3]==['PING','PING']
    assert json.loads(sent[3])['action']=='unsubscribe'
    assert json.loads(sent[4])['action']=='subscribe'


def test_socket_message_uses_matching_feed_and_updates_display(js):
    js.eval(WS_STUB)
    matching_oracle_market(js)
    js.eval(f'Date.now=()=>{TS+10}000;startOracle();sockets[0].readyState=1;sockets[0].onopen()')
    m=oracle_message(TS,100)
    m['payload']['data'].append({'timestamp':(TS+9)*1000,'value':101})
    js.eval(f'sockets[0].onmessage({{data:{json.dumps(json.dumps(m))}}})')
    assert js.eval('$("reference-direction").textContent')=='UP'
    assert js.eval('$("price-to-beat").textContent')=='$100.00'


def test_pause_closes_socket_and_resume_reconnects(js):
    js.eval(WS_STUB)
    js.eval('startOracle();sockets[0].readyState=1;$("pause").listeners.click()')
    assert js.eval('sockets[0].readyState')==3
    assert js.eval('state.oracle.socket') is None
    js.eval('$("pause").listeners.click()')
    assert js.eval('sockets.length')==2


def test_transport_failure_suppresses_comparison_and_schedules_retry(js):
    js.eval(WS_STUB)
    js.eval('startOracle();sockets[0].readyState=1;sockets[0].onerror()')
    assert js.eval('state.oracle.socket') is None
    assert js.eval('state.oracle.attempts')==1
    assert js.eval('timeoutCalls.length')>=2


def test_manual_price_applies_from_button_without_affecting_model(js):
    js.eval('$("reference-input").value="81,500.25";$("apply-reference").listeners.click()')
    assert js.eval('state.oracle.reference.price')==81500.25
    assert js.eval('MODEL')=='browser-candle-baseline-v1'
    assert js.eval('state.records.length')==0


def test_old_stored_reference_not_used_for_new_window(js):
    oracle_state(js)
    js.eval('saveReference(state.oracle.reference);state.oracle.reference=null;Date.now=()=>'+str((TS+300)*1000)+';loadReference();renderOracle()')
    assert js.eval('state.oracle.reference') is None
    assert js.eval('$("reference-direction").textContent')=='WAITING'


@pytest.mark.parametrize('code',[
    'state.lastCurrent=null','state.lastCurrent.source="https://other.example"',
    'state.lastCurrent.raw.cryptoMarketConfig.twapLookbackSeconds=30',
    'state.lastCurrent.raw.cryptoMarketConfig.twapEnabled=false',
    'state.lastCurrent.raw.cryptoMarketConfig.asset="eth"',
    'state.lastCurrent.raw.endDate="2020-01-01T00:00:00Z"',
    'state.lastCurrent.raw.eventStartTime="2020-01-01T00:00:00Z"',
    'state.lastCurrent.raw.slug="wrong-market"',
])
def test_price_comparison_requires_matching_market_rules(js,code):
    oracle_state(js)
    js.eval(code+';renderOracle()')
    assert js.eval('$("reference-direction").textContent')=='WAITING'
    assert 'market metadata' in js.eval('$("reference-detail").textContent')


def chart_snapshot(js,seconds,prices=None):
    prices=prices or [100+i for i in range(len(seconds))]
    m=oracle_message(TS)
    m['payload']['data']=[{'timestamp':(TS+s)*1000,'value':p} for s,p in zip(seconds,prices)]
    return js.eval(f'ingestOracleMessage({json.dumps(m)})')


def test_twap_history_keeps_sorted_unique_real_points(js):
    oracle_state(js)
    chart_snapshot(js,[22,20,21],[102,100,101])
    chart_snapshot(js,[21,23],[101.5,103])
    points=value(js,'oracleChartData().points')
    assert [p['exchange_ts'] for p in points]==[TS+20,TS+21,TS+22,TS+23]
    assert points[1]['price']==101.5


def test_twap_chart_never_backfills_before_first_observation(js):
    oracle_state(js)
    chart_snapshot(js,[25])
    g=value(js,'oracleChartGeometry(oracleChartData(),oracleComparison().reference)')
    assert len(value(js,'oracleChartData().points'))==1
    assert g['path'].startswith('M73.00 ')
    assert 'L' not in g['path']


def test_twap_chart_does_not_draw_across_missing_intervals(js):
    oracle_state(js)
    chart_snapshot(js,[10,11,20,21])
    path=js.eval('oracleChartGeometry(oracleChartData(),oracleComparison().reference).path')
    assert path.count('M')==2 and path.count('L')==2


def test_twap_chart_scale_includes_distant_reference(js):
    oracle_state(js,reference=200)
    chart_snapshot(js,[20,21],[100,101])
    g=value(js,'oracleChartGeometry(oracleChartData(),oracleComparison().reference)')
    assert g['low']<100 and g['high']>200
    assert 24<g['referenceY']<244


def test_twap_chart_flat_series_has_finite_coordinates(js):
    oracle_state(js)
    chart_snapshot(js,[20,21],[100,100])
    g=value(js,'oracleChartGeometry(oracleChartData(),oracleComparison().reference)')
    assert g['low']<100<g['high']
    assert 'NaN' not in g['path'] and 'Infinity' not in g['path']


def test_twap_chart_without_reference_still_draws_observations(js):
    oracle_state(js)
    chart_snapshot(js,[20,21])
    js.eval('state.oracle.reference=null;renderOracle()')
    assert js.eval('$("twap-path").getAttribute("d")').startswith('M')
    assert js.eval('$("twap-reference-line").getAttribute("visibility")')=='hidden'
    assert 'opening reference missing' in js.eval('$("twap-chart-status").textContent')
    assert js.eval('oracleComparison().direction') is None


@pytest.mark.parametrize('change',[
    'state.paused=true',
    'state.oracle.socket.readyState=3',
    'state.oracle.latest.exchange_ts=now()-21',
])
def test_twap_chart_preserves_history_but_labels_nonlive_feed(js,change):
    oracle_state(js)
    chart_snapshot(js,[20,21])
    js.eval(change+';renderOracle()')
    assert js.eval('$("twap-path").getAttribute("d")').startswith('M')
    assert js.eval('$("twap-chart").getAttribute("data-fresh")')=='false'
    assert 'historical observations' in js.eval('$("twap-chart-status").textContent')
    assert js.eval('$("reference-direction").textContent')=='WAITING'


def test_twap_chart_resets_on_boundary_without_new_messages(js):
    oracle_state(js)
    chart_snapshot(js,[20,21])
    js.eval(f'renderOracle();Date.now=()=>{TS+300}000;renderOracle()')
    assert js.eval('state.oracle.history.length')==0
    assert js.eval('$("twap-path").getAttribute("d")')==''
    assert js.eval('$("twap-last-point").getAttribute("visibility")')=='hidden'
    assert js.eval('$("twap-reference-line").getAttribute("visibility")')=='hidden'


def test_twap_chart_filters_previous_window_snapshot_points(js):
    oracle_state(js)
    chart_snapshot(js,[-2,-1,0,1])
    assert [p['exchange_ts'] for p in value(js,'oracleChartData().points')]==[TS,TS+1]


def test_twap_chart_does_not_display_future_timestamp(js):
    oracle_state(js)
    chart_snapshot(js,[29,31])
    assert [p['exchange_ts'] for p in value(js,'oracleChartData().points')]==[TS+29]


def test_twap_chart_rejects_wrong_feed_without_history_changes(js):
    oracle_state(js)
    chart_snapshot(js,[20])
    m=oracle_message(TS+21);m['payload']['window_s']=30
    assert js.eval(f'ingestOracleMessage({json.dumps(m)})') is False
    assert len(value(js,'oracleChartData().points'))==1


def test_twap_chart_hidden_for_unverified_market_metadata(js):
    oracle_state(js)
    chart_snapshot(js,[20,21])
    js.eval('state.lastCurrent.raw.cryptoMarketConfig.twapEnabled=false;renderOracle()')
    assert js.eval('$("twap-path").getAttribute("d")')==''
    assert 'not yet verified' in js.eval('$("twap-chart-status").textContent')


def test_twap_chart_reference_line_marks_manual_source(js):
    oracle_state(js,source='manual')
    chart_snapshot(js,[20,21])
    js.eval('renderOracle()')
    assert 'MANUAL' in js.eval('$("twap-reference-label").textContent')
    assert js.eval('$("twap-reference-line").getAttribute("visibility")')=='visible'


def test_twap_chart_bounded_to_current_window(js):
    oracle_state(js)
    js.eval(f'Date.now=()=>{TS+299}000')
    chart_snapshot(js,list(range(-299,300)))
    assert js.eval('state.oracle.history.length')==300
    assert len(value(js,'oracleChartData().points'))==300


def test_twap_chart_and_new_layout_leave_journal_storage_unchanged(js):
    oracle_state(js)
    before=js.eval('localStorage.getItem(KEY)')
    chart_snapshot(js,[0,1,2])
    js.eval('renderOracle()')
    assert js.eval('localStorage.getItem(KEY)')==before


def test_live_chart_is_primary_and_forecasts_are_collapsed():
    html=(ROOT/'index.html').read_text()
    supporting=html.split('<details class="supporting-context">',1)[1].split('</details>',1)[0]
    assert 'class="forecast-stack"' in supporting and 'id="chart"' in supporting
    assert 'id="twap-chart"' not in supporting
    assert html.index('id="reference-heading"')<html.index('id="twap-chart"')<html.index('id="draft-direction"')
    assert 'aria-labelledby="twap-chart-title twap-chart-description"' in html


def test_late_arrival_shows_reference_needed_not_generic_waiting(js):
    oracle_state(js)
    js.eval('state.oracle.reference=null;renderOracle()')
    assert js.eval('$("reference-direction").textContent')=='REFERENCE NEEDED'
    assert js.eval('$("connection").textContent')=='LIVE · REFERENCE NEEDED'
    assert js.eval('$("reference-controls").open') is True
    assert js.eval('$("reference-action").hidden') is False
    assert 'chart is receiving live data' in js.eval('$("reference-detail").textContent')
    assert js.eval('$("reference-market-link").href')==f'https://polymarket.com/event/btc-updown-5m-{TS}'


def test_manual_input_resolves_reference_needed_without_fabricating_side(js):
    oracle_state(js,price=99)
    js.eval('state.oracle.reference=null;renderOracle();setManualReference("100",state.oracle.inputWindow);renderOracle()')
    assert js.eval('$("reference-direction").textContent')=='DOWN'
    assert js.eval('$("reference-action").hidden') is True
    assert js.eval('$("connection").textContent')=='TWAP LIVE'
    assert 'MANUAL' in js.eval('$("reference-source").textContent')


def test_automatic_reference_closes_manual_form(js):
    oracle_state(js)
    js.eval('renderOracle()')
    assert js.eval('$("reference-controls").open') is False
    assert js.eval('$("reference-input").disabled') is True


def test_connection_badge_is_not_fooled_by_live_coinbase(js):
    oracle_state(js)
    js.eval('state.price={price:90000,exchange_ts:now(),received_at:now()};state.oracle.socket.readyState=3;render()')
    assert js.eval('$("connection").textContent')=='TWAP UNAVAILABLE'
    assert js.eval('$("reference-direction").textContent')=='WAITING'


def test_new_window_reopens_missing_reference_form(js):
    oracle_state(js)
    js.eval(f'renderOracle();Date.now=()=>{TS+300}000;renderOracle()')
    assert js.eval('$("reference-controls").open') is True
    assert js.eval('$("reference-action").hidden') is False
    assert js.eval('$("reference-market-link").href')==f'https://polymarket.com/event/btc-updown-5m-{TS+300}'