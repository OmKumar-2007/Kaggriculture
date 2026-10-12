#!/usr/bin/env python3
"""Optional real browser check of 50 logged-in contestants' analytics and replay controls.

Requires `py -3 -m pip install playwright` and `py -3 -m playwright install chromium`.
Uses only saved participant cookies; never registers accounts or submits jobs.
"""
from __future__ import annotations
import argparse,csv,json,sys,time
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parent

def main():
    try:from playwright.sync_api import sync_playwright
    except ImportError:raise SystemExit('Install Playwright: py -3 -m pip install playwright; py -3 -m playwright install chromium')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frontend',default='https://neural-coliseum.onrender.com')
    p.add_argument('--api',default='https://neural-coliseum-api.onrender.com')
    p.add_argument('--wave',type=int,choices=(1,2),required=True)
    p.add_argument('--limit',type=int,default=50)
    p.add_argument('--headed',action='store_true')
    a=p.parse_args()
    if not 1<=a.limit<=50:raise SystemExit('limit 1-50')
    if a.frontend.rstrip('/')!='https://neural-coliseum.onrender.com' or a.api.rstrip('/')!='https://neural-coliseum-api.onrender.com':
        print('Custom origins requested: ensure target matches cookies and is authorized.')
    state=json.loads((ROOT/'runtime'/'state.json').read_text(encoding='utf-8'))
    if state['target']!=a.api.rstrip('/'):raise SystemExit('API does not match saved session target')
    teams=list(csv.DictReader((ROOT/'teams.csv').open(encoding='utf-8',newline='')))[:a.limit]
    out=[]
    with sync_playwright() as play:
        browser=play.chromium.launch(headless=not a.headed)
        for i,row in enumerate(teams,1):
            team=row['team'];context=None
            try:
                job=state['teams'][team]['sandbox'].get(str(a.wave),{})
                rid=job.get('replayId')
                if job.get('status')!='completed' or not rid:raise RuntimeError('Missing completed sandbox and replay ID')
                jar=MozillaCookieJar(str(ROOT/'runtime'/'sessions'/f'{team}.cookies.txt'));jar.load(ignore_discard=True,ignore_expires=True)
                context=browser.new_context(ignore_https_errors=False)
                cookie_name='farmcraft_participant'
                cookies=[{'name':c.name,'value':c.value,'domain':urlparse(a.api).hostname,'path':'/','httpOnly':True,
                          'secure':True,'sameSite':'None'} for c in jar if c.name==cookie_name]
                if len(cookies)!=1:raise RuntimeError('Exactly one valid participant session cookie required')
                context.add_cookies(cookies)
                page=context.new_page();errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                requests=[]
                page.on('response',lambda resp: requests.append((resp.status,resp.url)) if '/replays/' in resp.url else None)
                page.goto(a.frontend,wait_until='domcontentloaded',timeout=60_000)
                page.get_by_role('button',name='analytics',exact=True).click(timeout=35_000)
                page.get_by_text('MATCH REPLAY').wait_for(timeout=50_000)
                speed=page.locator('.replay-speed')
                if speed.inner_text().strip()!='10×':raise RuntimeError('Replay speed does not show fixed 10×')
                if page.locator('.replay-controls select').count()!=0:raise RuntimeError('Unexpected replay speed select')
                page.get_by_role('button',name='Play',exact=True).click(timeout=10_000)
                page.get_by_role('button',name='Pause',exact=True).wait_for(timeout=8_000)
                time.sleep(.36)
                progress=int(page.get_by_role('slider',name='Replay turn').input_value())
                if not 3<=progress<=11:
                    raise RuntimeError(f'Expected roughly 10× playback (~6 turns/360 ms), observed {progress} turns')
                page.get_by_role('button',name='Pause',exact=True).click()
                page.get_by_role('button',name='Next',exact=True).click()
                slider=page.get_by_role('slider',name='Replay turn')
                slider.fill('5')
                if slider.input_value()!='5':raise RuntimeError('Seek failed')
                playback_responses=[(status,url) for status,url in requests if '/playback' in url]
                if not playback_responses or any(status!=200 for status,url in playback_responses):
                    raise RuntimeError('Replay playback GET absent or failed')
                if not any(rid in url for status,url in playback_responses):
                    raise RuntimeError('Browser displaying a different replay from requested wave')
                if errors:raise RuntimeError('JavaScript exception: '+errors[0][:200])
                out.append({'team':team,'wave':a.wave,'ok':True,'replayId':rid,'networkReplayRequests':len(requests)})
                print(f'[{i:02d}/{len(teams)}] browser analytics + 10× replay OK: {team}',flush=True)
            except Exception as e:
                out.append({'team':team,'wave':a.wave,'ok':False,'error':str(e)[:300]})
                print(f'[{i:02d}/{len(teams)}] browser FAILED {team}: {str(e)[:170]}',flush=True)
            finally:
                if context:context.close()
            (ROOT/'runtime'/f'browser_wave_{a.wave}.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
        browser.close()
    passed=sum(x['ok'] for x in out)
    print(f'Browser checked {passed}/{len(out)}; saved runtime/browser_wave_{a.wave}.json')
    return 0 if passed==len(teams) else 2
if __name__=='__main__':sys.exit(main())
