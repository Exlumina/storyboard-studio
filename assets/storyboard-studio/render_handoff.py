"""Read/receive local immutable storyboard requests and publish actual native returns."""
import argparse,json,urllib.request

def call(base,path,method='GET',value=None):
    return json.load(urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(value).encode() if value is not None else None,method=method,headers={'Content-Type':'application/json'}),timeout=30))

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['pending','receive','publish','check-plan']);p.add_argument('--base',default='http://127.0.0.1:8840');p.add_argument('--request');p.add_argument('--owner');p.add_argument('--note');p.add_argument('--manifest');p.add_argument('--mapping');a=p.parse_args()
    if a.action=='pending':
        rows=[]
        for b in call(a.base,'/api/boards')['items']:
            rows += [r for r in call(a.base,'/api/storyboard-requests?board_id='+b['id'])['items'] if r['status'] in ('requested','received_by_render_owner')]
        print(json.dumps({'requests':rows,'automatic_renderer_started':False},indent=2));return
    if not a.request:p.error('--request is required')
    if a.action=='check-plan':
        if not a.mapping:p.error('--mapping is required')
        from storyboard_conformance import validate
        with open(a.mapping) as f:mapping=json.load(f)
        result=validate(call(a.base,'/api/storyboard-requests/'+a.request),mapping)
        print(json.dumps(result,indent=2))
        raise SystemExit(bool(result['errors']))
    if a.action=='receive':
        if not a.owner or not a.note:p.error('--owner and --note are required after reading the immutable brief')
        value=call(a.base,'/api/storyboard-requests/'+a.request+'/receive','POST',{'owner':a.owner,'note':a.note})
    else:
        if not a.manifest:p.error('--manifest with actual native completion and frame hashes is required')
        with open(a.manifest) as f:manifest=json.load(f)
        value=call(a.base,'/api/storyboard-requests/'+a.request+'/results','POST',{'manifest':manifest})
    print(json.dumps(value,indent=2))
if __name__=='__main__':main()
