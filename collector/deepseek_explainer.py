"""Local-only DeepSeek explanation panel for real, frozen horizon forecasts.

No model training or trading. Paid inference is disabled unless explicitly enabled.
"""
import argparse
import getpass
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

MODEL = 'deepseek-ai/DeepSeek-V4.1-Flash'
ENDPOINT = 'https://api.inference.wandb.ai/v1/chat/completions'
PROJECT = 'pbernoos-university-of-michigan/wandb_agent_default_project'
NOTES = {
    'research_only': 'Research forecast: predictive accuracy and profitability have not been established.',
    'direction_not_settlement': 'These directions describe the BTC TWAP relative to its window-start value, not the five-minute contract outcome.',
    'uncertain': 'At least one horizon has an Up probability between 40% and 60%; direction is uncertain.',
    'mixed': 'The forecast directions differ across horizons; this does not identify an exact turning point.',
    'aligned': 'All three horizon probabilities lean in the same direction; this is not a guarantee.',
    'costs': 'Entry decisions also require settlement probabilities, executable ask prices, fees and uncertainty.',
}


def validate_forecast(raw, now_ns=None):
    now_ns = time.time_ns() if now_ns is None else now_ns
    required = {'schema','window','generated_ns','cutoff_ns','model_version','probabilities','data_complete','research_only'}
    if not isinstance(raw,dict) or set(raw) != required or raw['schema'] != 'frozen-horizon-forecast-v1':
        raise ValueError('Expected a frozen-horizon-forecast-v1 record; no predictions fabricated')
    for k in ('window','generated_ns','cutoff_ns'):
        if type(raw[k]) is not int or raw[k] <= 0:
            raise ValueError('Invalid forecast timestamps')
    t = raw['window']
    if t % 300 or not raw['cutoff_ns'] <= raw['generated_ns'] <= t*10**9 or raw['cutoff_ns'] >= t*10**9:
        raise ValueError('Forecast was not frozen by window start')
    if raw['cutoff_ns'] < (t-30)*10**9:
        raise ValueError('Forecast inputs are too old')
    if not t*10**9 <= now_ns < (t+300)*10**9:
        raise ValueError('Forecast is not for the current five-minute window')
    if raw['data_complete'] is not True or raw['research_only'] is not True:
        raise ValueError('Complete, explicitly research-only forecast required')
    if not isinstance(raw['model_version'],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',raw['model_version']):
        raise ValueError('Invalid numerical-model version')
    probs = raw['probabilities']
    if not isinstance(probs,dict) or set(probs) != {'60','120','180'}:
        raise ValueError('All three horizon probabilities are required')
    for p in probs.values():
        if type(p) not in (int,float) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError('Invalid probability')
    # A schema check cannot authenticate provenance: production must read the
    # actual immutable model journal, not arbitrary user-written forecast files.
    return raw


def eligible_notes(forecast):
    p = list(forecast['probabilities'].values())
    codes = ['research_only','direction_not_settlement','costs']
    if any(.4 <= x <= .6 for x in p):
        codes.append('uncertain')
    if any(x > .5 for x in p) and any(x < .5 for x in p):
        codes.append('mixed')
    elif all(x > .5 for x in p) or all(x < .5 for x in p):
        codes.append('aligned')
    return codes


def inference(key, request):
    encoded = json.dumps(request,allow_nan=False).encode()
    req = urllib.request.Request(ENDPOINT, data=encoded, method='POST', headers={
        'Authorization':'Bearer '+key, 'OpenAI-Project':PROJECT, 'Content-Type':'application/json'})
    # Never follow redirects with an authorization header. No endpoint override.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(req,timeout=10) as response:
        body = response.read(100001)
        if len(body)>100000:
            raise ValueError('Oversized inference response')
        return json.loads(body)


class Explainer:
    def __init__(self, path, key='', allow_paid=False, max_calls=3, transport=inference):
        if type(max_calls) is not int or not 1 <= max_calls <= 20:
            raise ValueError('Call cap must be 1..20 per server session')
        self.path = Path(path)
        self.key, self.allow_paid, self.max_calls = key, allow_paid, max_calls
        self.calls = 0
        self.cache = {}
        self.transport = transport

    def load(self, now_ns=None):
        if not self.path.is_file():
            raise ValueError('Waiting for an actual frozen three-horizon forecast; the model is not connected yet')
        if self.path.stat().st_size > 16000:
            raise ValueError('Forecast file too large')
        return validate_forecast(json.loads(self.path.read_text()),now_ns)

    def explain(self, now_ns=None):
        f = self.load(now_ns)
        result = dict(status='local_notes', model=MODEL, probabilities=f['probabilities'],
            numerical_model=f['model_version'], window=f['window'],
            notes=[NOTES[c] for c in eligible_notes(f)],
            warning='No buy/sell instructions. Commentary cannot change numerical forecasts.', calls_used=self.calls)
        if not self.allow_paid:
            result['warning'] += ' Paid inference disabled; these are deterministic local notes, not DeepSeek output.'
            return result
        token = hashlib.sha256(json.dumps(f,sort_keys=True).encode()).hexdigest()
        if token in self.cache:
            return self.cache[token]
        if not self.key:
            result['warning'] += ' Missing server-side credential; no inference request sent.'
            return result
        if self.calls >= self.max_calls:
            result['warning'] += ' Session call cap reached; no inference request sent.'
            return result
        codes = eligible_notes(f)
        request = dict(model=MODEL,max_tokens=512,messages=[
            {'role':'system','content':'Rank the supplied evidence-backed explanation note codes. Return ONLY JSON {"reason_codes":[...]} with 1 to 3 distinct allowed codes. No prose, predictions, prices, trading instructions or new codes. This is a research explanation, not a forecast.'},
            {'role':'user','content':json.dumps({'horizon_probabilities':f['probabilities'],
                'allowed_notes':{c:NOTES[c] for c in codes}})}])
        self.calls += 1
        try:
            response = self.transport(self.key,request)
            if response.get('model') != MODEL:
                raise ValueError('Served model identity did not match requested model')
            choice = response['choices'][0]
            if choice.get('finish_reason') != 'stop':
                raise ValueError('Incomplete model output')
            parsed = json.loads(choice['message']['content'])
            selected = parsed.get('reason_codes') if isinstance(parsed,dict) else None
            if not isinstance(parsed,dict) or set(parsed) != {'reason_codes'} or not isinstance(selected,list) or not 1 <= len(selected) <= 3 or any(not isinstance(x,str) for x in selected) or len(set(selected)) != len(selected) or any(x not in codes for x in selected):
                raise ValueError('Unapproved explanation output')
            result.update(status='deepseek_ranked_notes',priority_notes=[NOTES[x] for x in selected],
                usage=response.get('usage'),calls_used=self.calls)
        except Exception:
            # Do not leak response bodies, request headers or credentials.
            result.update(status='local_fallback',calls_used=self.calls)
            result['warning'] += ' DeepSeek request/output failed validation; local notes retained. Failed requests may still consume credits.'
        # Cache failures too; refreshing cannot trigger an automatic paid retry.
        self.cache[token] = result
        return result


PAGE = b'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Local forecast explanation</title>
<h1>Research forecast explanation</h1><p>Local only. No trading. Requires an actual frozen current-window forecast.</p>
<p>Pressing Explain uses inference credits ONLY if the server was started with --allow-paid-inference. Max 3 calls per session by default.</p>
<button id="explain">Explain current forecast</button><pre id="result">Waiting. No forecasts invented.</pre>
<script src="/panel.js"></script></html>'''
SCRIPT = b'''document.getElementById('explain').onclick=async()=>{const out=document.getElementById('result');try{const r=await fetch('/api/explain',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});out.textContent=JSON.stringify(await r.json(),null,2);}catch(e){out.textContent='Local service unavailable.';}};'''


def handler(explainer, port):
    origin = 'http://127.0.0.1:'+str(port)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def send(self,status,payload,ctype='application/json'):
            data = payload if isinstance(payload,bytes) else json.dumps(payload,allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type',ctype)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)
        def allowed(self):
            return self.headers.get('Host') == '127.0.0.1:'+str(port)
        def do_GET(self):
            if not self.allowed():
                return self.send(403,{'error':'Local host required'})
            if self.path == '/':
                return self.send(200,PAGE,'text/html; charset=utf-8')
            if self.path == '/panel.js':
                return self.send(200,SCRIPT,'text/javascript; charset=utf-8')
            return self.send(404,{'error':'Not found'})
        def do_POST(self):
            if not self.allowed() or self.headers.get('Origin') != origin:
                return self.send(403,{'error':'Same-origin local browser required'})
            if self.path != '/api/explain':
                return self.send(404,{'error':'Not found'})
            if self.headers.get('Content-Type') != 'application/json' or self.headers.get('Content-Length') != '2' or self.rfile.read(2) != b'{}':
                return self.send(400,{'error':'Empty JSON object required'})
            try:
                self.send(200,explainer.explain())
            except (ValueError,OSError,KeyError,TypeError):
                self.send(409,{'status':'waiting_or_invalid','error':'No valid frozen current-window forecast. No inference request sent.'})
    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--forecast',required=True,help='Actual immutable numerical forecast record, not training targets')
    p.add_argument('--port',type=int,default=8766)
    p.add_argument('--allow-paid-inference',action='store_true')
    p.add_argument('--max-calls',type=int,default=3)
    a = p.parse_args()
    if not 1024 <= a.port <= 65535 or not 1 <= a.max_calls <= 20:
        p.error('Port must be 1024..65535; call cap 1..20')
    key = ''
    if a.allow_paid_inference:
        key = os.environ.get('WANDB_API_KEY') or getpass.getpass('W&B Inference API key (hidden, memory only): ')
    e = Explainer(a.forecast,key,a.allow_paid_inference,a.max_calls)
    server = HTTPServer(('127.0.0.1',a.port),handler(e,a.port))
    print('Local panel: http://127.0.0.1:'+str(a.port),flush=True)
    print('Paid inference '+('ENABLED' if a.allow_paid_inference else 'DISABLED')+'; no training, forecasts or trades created.',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()