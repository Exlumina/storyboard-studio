"""Supported local feedback handoff. Print pending descriptions; receive/ack explicitly."""
import argparse,json,urllib.request

def call(base,path,method='GET',value=None):
    req=urllib.request.Request(base+path,data=json.dumps(value).encode() if value is not None else None,method=method,headers={'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req,timeout=10))

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['pending','receive','acknowledge']);p.add_argument('--base',default='http://127.0.0.1:8840');p.add_argument('--id');p.add_argument('--actor',default='Codex');p.add_argument('--note');a=p.parse_args()
    if a.action=='pending':
        boards=call(a.base,'/api/boards')['items'];requests=[]
        for board in boards:
            for r in call(a.base,'/api/scene-requests?board_id='+board['id'])['items']:
                if r['status'] in ('queued_for_chat','received_by_codex'):requests.append(r)
        print(json.dumps({'local_handoff_only':True,'renderer_started':False,'requests':requests},indent=2));return
    if not a.id or not a.note:p.error('--id and --note are required; use a real acknowledgement after reading the description')
    print(json.dumps(call(a.base,'/api/scene-requests/'+a.id+'/'+a.action,'POST',{'actor':a.actor,'note':a.note}),indent=2))
if __name__=='__main__':main()
