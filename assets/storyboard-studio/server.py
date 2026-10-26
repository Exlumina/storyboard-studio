"""Local, project-scoped storyboard persistence and reference media service."""
import render_return
import storyboard_reader
import shutil
import sys
import argparse, hashlib, json, math, mimetypes, os, re, subprocess, tempfile, threading, uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs

LOCK = threading.RLock()
CLIP_LOCK = threading.Lock()
ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'

def read(path, fallback=None):
    return json.loads(path.read_text()) if path.exists() else fallback

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as f:
        json.dump(value, f, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
    temp.replace(path)

def media_tool(name):
    path=shutil.which(name)
    if not path:raise ValueError(f'{name} is required for media imports and bounded playback. Install FFmpeg and add its executables to PATH.')
    return path

def copy_local_identifier(value):
    text=value.get('text')
    if not isinstance(text,str) or not text or len(text)>160:raise ValueError('Choose a saved project identifier to copy.')
    codes=read(DATA/'short-identities.json',{'codes':{}}).get('codes',{})
    allowed=set(codes.values())|{p.stem for p in (DATA/'boards').glob('*.json') if re.fullmatch(r'[a-f0-9]{32}',p.stem)}
    allowed.add(project().get('id'))
    if text not in allowed:raise ValueError('This identifier is not registered in this project. Save the card before copying.')
    if sys.platform!='darwin':return {'native_supported':False,'copied':False}
    writer,reader=shutil.which('pbcopy'),shutil.which('pbpaste')
    if not writer or not reader:return {'native_supported':True,'copied':False,'error':'macOS clipboard tools are unavailable.'}
    try:
        subprocess.run([writer],input=text.encode('utf-8'),check=True,timeout=3)
        actual=subprocess.check_output([reader],timeout=3).decode('utf-8')
        if actual!=text:raise ValueError('The Mac clipboard did not retain this ID. Try copying again.')
        return {'native_supported':True,'copied':True}
    except (OSError,subprocess.SubprocessError,UnicodeError,ValueError):
        return {'native_supported':True,'copied':False,'error':'Could not verify the Mac clipboard. Select and copy the ID manually.'}

def utc_now(): return datetime.now(timezone.utc).isoformat()

def board_file(board_id):
    if not isinstance(board_id,str) or not re.fullmatch(r'[a-f0-9]{32}',board_id):
        raise ValueError('Invalid board ID.')
    return DATA/'boards'/f'{board_id}.json'

def active_state(): return read(DATA/'active_board.json',{})
def active_id(): return active_state().get('active_id')
def get_board(board_id=None):
    value=read(board_file(board_id or active_id()))
    if value is None: raise ValueError('Board not found.')
    return board_short_identities(value)

def short_identity(kind, identity):
    """Stable compact alias; original UUID/reference identity remains authoritative."""
    if kind not in ('S', 'R') or not identity: raise ValueError('A scene or reference identity is required.')
    key=kind+':'+str(identity)
    with LOCK:
        registry=read(DATA/'short-identities.json', {'codes':{}})
        codes=registry['codes']
        if key not in codes:
            alphabet='0123456789ABCDEFGHJKMNPQRSTVWXYZ'; used=set(codes.values()); salt=0
            while True:
                value=int.from_bytes(hashlib.sha256((key+':'+str(salt)).encode()).digest()[:4], 'big') & ((1<<25)-1)
                code=kind+''.join(alphabet[(value>>shift)&31] for shift in (20,15,10,5,0))
                if code not in used: break
                salt+=1
            codes[key]=code;save(DATA/'short-identities.json', registry)
        return codes[key]

def board_short_identities(board):
    result=dict(board);result['nodes']=[dict(n,short_id=short_identity('S',n['scene_id'])) if n.get('scene_id') and n.get('kind','scene')=='scene' else dict(n) for n in board.get('nodes',[])]
    return result

def base36(value):
    alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';out=''
    while value: value,digit=divmod(value,36);out=alphabet[digit]+out
    return out or '0'

def scene_display_code(scene_id):
    """Project-wide, durable short identity. Deleted codes are never recycled."""
    registry=read(DATA/'scene-identities.json',{'next':1,'codes':{}})
    if scene_id not in registry['codes']:
        registry['codes'][scene_id]='S'+base36(registry['next'])
        registry['next']+=1;save(DATA/'scene-identities.json',registry)
    return registry['codes'][scene_id]

def ensure_scene_ids(board, previous=None, duplicate=False):
    """Assign missing identity once, keeping graph node IDs and edges intact."""
    result=dict(board);prior={n.get('id'):n for n in (previous or {}).get('nodes',[])}
    result['nodes']=[]
    for source in board.get('nodes',[]):
        n=dict(source)
        if n.get('kind','scene')=='scene':
            original=n.get('scene_id') or prior.get(n.get('id'),{}).get('scene_id')
            if duplicate:
                if original:n['source_scene_id']=original
                n['scene_id']='scn_'+uuid.uuid4().hex
            else:n['scene_id']=original or 'scn_'+uuid.uuid4().hex
            n['scene_code']=scene_display_code(n['scene_id'])
            if 'short_id' in n:n['short_id']=short_identity('S',n['scene_id'])
        result['nodes'].append(n)
    return result

def migrate_snapshot_scene_ids():
    for file in (DATA/'snapshots').glob('*.json'):
        original=read(file)
        if not isinstance(original.get('board'),dict):continue
        bid=snapshot_board_id(original)
        previous=read(board_file(bid)) or read(DATA/'archived-boards'/bid/(bid+'.json')) or original['board']
        migrated=dict(original,board=ensure_scene_ids(original['board'],previous))
        if migrated!=original:
            backup=DATA/'migration-backups'/'snapshots'/file.name
            if not backup.exists():save(backup,original)
            save(file,migrated)

def validate_schema(board):
    if not isinstance(board,dict):raise ValueError('Board must be an object.')
    version=board.get('schema_version',1)
    if type(version) is not int or version!=1:raise ValueError('Unsupported storyboard schema version. Preserve this board and use a compatible Studio version.')

def initialize_board_store():
    """Startup-only migration. Preserve the exact pre-store source once."""
    with LOCK:
        # Preflight every migration target before writing identities or backups.
        candidates=[DATA/'board.json',*(DATA/'boards').glob('*.json'),*(DATA/'snapshots').glob('*.json')]
        for file in candidates:
            if not file.is_file():continue
            value=read(file)
            if isinstance(value,dict):validate_schema(value.get('board',value))
        if active_id():
            for file in (DATA/'boards').glob('*.json'):
                if not re.fullmatch(r'[a-f0-9]{32}\.json',file.name):continue
                original=read(file);migrated=ensure_scene_ids(original)
                if migrated!=original:
                    backup=file.with_suffix('.pre-scene-ids.json')
                    if not backup.exists():save(backup,original)
                    save(file,migrated)
            migrate_snapshot_scene_ids()
            save(DATA/'board.json',get_board())
            return
        original=read(DATA/'board.json')
        if original is not None:
            if not (DATA/'board.pre-store.json').exists():save(DATA/'board.pre-store.json',original)
            board=dict(original)
        else:
            board={'title':'Untitled storyboard','asset_policy':'latest-approved','nodes':[],'edges':[],
                   'effects':[],'chosen_path':[],'marker_supported':True}
        board['board_id']=uuid.uuid4().hex
        board.setdefault('title','Untitled storyboard')
        board.setdefault('revision',0)
        board.setdefault('created_utc',utc_now());board.setdefault('updated_utc',utc_now())
        board=ensure_scene_ids(board)
        save(board_file(board['board_id']),board)
        save(DATA/'active_board.json',{'active_id':board['board_id'],'legacy_board_id':board['board_id']})
        migrate_snapshot_scene_ids()
        save(DATA/'board.json',board)

def save_board(value):
    validate_schema(value)
    bid=value.get('board_id') or active_id();old=get_board(bid)
    value=ensure_scene_ids(value,old);validate(value)
    result=dict(value,board_id=bid,revision=old.get('revision',0)+1,updated_utc=utc_now())
    result.setdefault('created_utc',old.get('created_utc',utc_now()))
    result.setdefault('title',old.get('title','Untitled storyboard'))
    save(board_file(bid).with_suffix('.previous.json'),old)
    save(board_file(bid),result)
    if bid==active_id():
        save(DATA/'board.previous.json',old);save(DATA/'board.json',result)
    return result

def activate_board(bid):
    board=get_board(bid);state=active_state();state['active_id']=bid
    save(DATA/'active_board.json',state);save(DATA/'board.json',board)
    return board

def create_board(value):
    title=str(value.get('title','Untitled storyboard')).strip()[:150]
    if not title:raise ValueError('Add a storyboard name.')
    source=value.get('duplicate_from')
    if source:
        board=ensure_scene_ids(get_board(source),duplicate=True);board['source_board_id']=source
    else:
        board={'asset_policy':'latest-approved','nodes':[],'edges':[],'effects':[],
               'chosen_path':[],'marker_supported':True}
    board.update(board_id=uuid.uuid4().hex,title=title,revision=0,created_utc=utc_now(),updated_utc=utc_now())
    save(board_file(board['board_id']),board)
    return board

def board_items():
    return [{'id':b['board_id'],'title':b.get('title','Untitled storyboard'),
             'updated_utc':b.get('updated_utc'),'node_count':len(b.get('nodes',[]))}
            for p in sorted((DATA/'boards').glob('*.json')) if re.fullmatch(r'[a-f0-9]{32}\.json',p.name)
            for b in [read(p)]]

def scoped_board(value):
    supplied=value.get('board')
    bid=value.get('board_id') or (supplied or {}).get('board_id') or active_id()
    stored=get_board(bid)
    if supplied is not None:
        if supplied.get('board_id') and supplied['board_id']!=bid:raise ValueError('Board IDs disagree.')
        return ensure_scene_ids(dict(supplied,board_id=bid,title=supplied.get('title',stored.get('title')),
                    revision=supplied.get('revision',stored.get('revision',0))),stored)
    return stored

def snapshot_board_id(snapshot):
    return snapshot.get('board_id') or snapshot.get('board',{}).get('board_id') or active_state().get('legacy_board_id')

def make_snapshot(board,name):
    sid=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8]
    result={'id':sid,'name':str(name)[:150],'created_utc':utc_now(),
            'board_id':board['board_id'],'board_title':board.get('title'),
            'board_revision':board.get('revision',0),'board':board}
    save(DATA/'snapshots'/f'{sid}.json',result)
    return result

def catalog():
    value=read(ROOT / 'catalog.json', {'items': []})
    return dict(value,items=[dict(item,short_id=short_identity('R',item['id'])) for item in value['items']])
def project(): return {'marker_supported':False, **read(ROOT / 'project.json', {})}
def rename_project(value):
    """Rename presentation only; preserve identity, approval policy and unknown fields."""
    if not isinstance(value,dict) or set(value)!={'title'}:
        raise ValueError('Only the project title can be changed.')
    title=value['title']
    if not isinstance(title,str) or not title.strip():raise ValueError('Add a project name.')
    title=title.strip()
    if len(title)>150:raise ValueError('Project names must be 150 characters or fewer.')
    with LOCK:
        path=ROOT/'project.json';current=read(path)
        if not isinstance(current,dict) or not current.get('id'):raise ValueError('Project configuration is unavailable.')
        if current.get('title')==title:return project()
        backup=DATA/'config-backups'/('project-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex+'.json')
        backup.parent.mkdir(parents=True,exist_ok=True)
        with backup.open('xb') as f:
            f.write(path.read_bytes());f.flush();os.fsync(f.fileno())
        save(path,dict(current,title=title))
        return project()
def effect_registry(): return read(ROOT/'effects.json',{'effects':[]})

def validate_reference_bounds(item,start,end):
    interval=item.get('source_interval',{})
    if interval.get('start_s') is not None and start<float(interval['start_s'])-1e-6:raise ValueError('Clip starts before this reference view. Choose a trim inside its source interval.')
    if end is not None and interval.get('end_s') is not None and end>float(interval['end_s'])+1e-6:raise ValueError('Clip ends after this reference view. Choose a trim inside its source interval.')

def auxiliary_targets(card):
    return card['target_node_ids'] if isinstance(card.get('target_node_ids'),list) else [card['parent_node_id']] if card.get('parent_node_id') else []

def validate(board, rendering=False):
    validate_schema(board)
    if board.get('asset_policy') != 'latest-approved': raise ValueError('Use the latest approved asset policy.')
    nodes, edges = board.get('nodes', []), board.get('edges', [])
    if not isinstance(nodes, list) or not isinstance(edges, list) or len(nodes)>1000 or len(edges)>4000:
        raise ValueError('Invalid or oversized graph.')
    scene_ids=[n.get('scene_id') for n in nodes if n.get('kind','scene')=='scene']
    if len(set(scene_ids))!=len(scene_ids) or any(not isinstance(i,str) or not re.fullmatch(r'scn_[a-f0-9]{32}',i) for i in scene_ids):raise ValueError('Scene IDs must be unique scn_ UUID identities.')
    ids = [n.get('id') for n in nodes]
    if len(set(ids))!=len(ids) or any(not isinstance(i,str) or not i for i in ids): raise ValueError('Scene IDs must be unique.')
    pairs=set();adj={i:[] for i in ids}
    byid={n['id']:n for n in nodes}
    for n in nodes:
        kind=n.get('kind','scene')
        if kind not in ('scene','start','end'):raise ValueError('Unknown card type.')
        for key in ('x','y','duration_s'):
            v=n.get(key,0)
            if not isinstance(v,(int,float)) or not math.isfinite(v): raise ValueError('Scene coordinates and duration must be finite.')
        if not isinstance(n.get('reference_images',[]),list) or any(not isinstance(r,str) for r in n.get('reference_images',[])):raise ValueError('Scene reference images must be reference IDs.')
        if kind=='scene' and n.get('duration_s',0)<=0: raise ValueError('Scene duration must be positive.')
        if kind in ('start','end') and n.get('duration_s',0)!=0:raise ValueError('Start and End cards do not add running time.')
    for e in edges:
        a,b=e.get('from'),e.get('to')
        if a not in adj or b not in adj or a==b or (a,b) in pairs: raise ValueError('Invalid or duplicate connection.')
        if byid[a].get('kind')=='end' or byid[b].get('kind')=='start':raise ValueError('Start cards have only outputs; End cards have only inputs.')
        if e.get('transition') not in ('cut','continuous'): raise ValueError('Choose Cut or Continuous camera move.')
        if byid[b].get('kind')=='end' and e.get('transition')!='cut':raise ValueError('End markers expose only a Cut input. Use Cut for connections into End.')
        pairs.add((a,b));adj[a].append(b)
    effects=board.get('effects',[])
    if not isinstance(effects,list) or len(effects)>4000:raise ValueError('Invalid effect cards.')
    for effect in effects:
        targets=auxiliary_targets(effect)
        if not isinstance(targets,list) or any(not isinstance(i,str) for i in targets) or len(set(targets))!=len(targets):raise ValueError('Effect targets must be unique scene IDs.')
        if any(i not in adj or byid[i].get('kind','scene')!='scene' for i in targets):raise ValueError('Attach effects to existing scene cards, not Start or End.')
        if effect.get('kind')!='lens_flare':raise ValueError('Unknown effect type.')
        intensity=effect.get('settings',{}).get('intensity',1)
        if not isinstance(intensity,(int,float)) or not math.isfinite(intensity) or not 0<=intensity<=10:raise ValueError('Effect intensity must be between 0 and 10.')
    feedback_cards=board.get('feedback_cards',[])
    if not isinstance(feedback_cards,list) or len(feedback_cards)>4000:raise ValueError('Invalid feedback cards.')
    for card in feedback_cards:
        if not isinstance(card.get('id'),str) or card.get('kind')!='feedback':raise ValueError('Feedback cards need a unique ID and feedback kind.')
        if not isinstance(card.get('text',''),str) or len(card.get('text',''))>12000:raise ValueError('Feedback must be text under 12,000 characters.')
        for key in ('x','y'):
            if not isinstance(card.get(key,0),(int,float)) or not math.isfinite(card.get(key,0)):raise ValueError('Feedback positions must be finite.')
        targets=auxiliary_targets(card)
        if len(set(targets))!=len(targets) or any(not isinstance(i,str) or i not in adj or byid[i].get('kind','scene')!='scene' for i in targets):raise ValueError('Attach feedback to existing scene cards only.')
    auxiliary_ids=[e.get('id') for e in effects]+[e.get('id') for e in feedback_cards]
    if len(set(auxiliary_ids))!=len(auxiliary_ids):raise ValueError('Auxiliary card IDs must be unique.')
    if rendering:
        active=board.get('chosen_path',board.get('order',[]))
        if not active: raise ValueError('Choose a render path first.')
        if project().get('marker_supported') and (byid.get(active[0],{}).get('kind')!='start' or byid.get(active[-1],{}).get('kind')!='end'):raise ValueError('Connect an explicit Start-to-End chosen path before execution.')
        if not any(byid.get(i,{}).get('kind','scene')=='scene' for i in active):raise ValueError('Connect scene cards between Start and End before requesting a storyboard.')
        if len(set(active))!=len(active) or any(i not in adj for i in active): raise ValueError('Render path contains repeated or missing scenes.')
        if adj[active[-1]] and not board.get('render_path_ends_here',False): raise ValueError('Choose the next branch or explicitly end the render path here.')
        if any((a,b) not in pairs for a,b in zip(active,active[1:])): raise ValueError('Connect every scene in the chosen path.')
        visiting=set();visited=set()
        def visit(i):
            if i in visiting: raise ValueError('Remove graph cycles before requesting a storyboard.')
            if i in visited:return
            visiting.add(i)
            for j in adj[i]:
                if j in active: visit(j)
            visiting.remove(i);visited.add(i)
        for i in active: visit(i)
        references={r['id']:r for r in catalog()['items']};refs=set(references)
        presets={p['id'] for entry in effect_registry()['effects'] for p in entry.get('presets',[])}
        for effect in effects:
            if any(i in active for i in auxiliary_targets(effect)) and effect.get('enabled',True) and effect.get('preset_id') not in presets:raise ValueError('Choose an installed preset for every enabled effect on the render path.')
        byid={n['id']:n for n in nodes}
        for i in active:
            n=byid[i]
            if n.get('kind','scene')!='scene':continue
            if n.get('reference_id') and n['reference_id'] not in refs: raise ValueError('A chosen scene has a missing reference.')
            if not n.get('reference_id') and not n.get('reference_images') and not str(n.get('description') or n.get('requested_changes') or '').strip():raise ValueError('Describe this scene or attach a visual reference before execution.')
            if any(rid not in refs for rid in n.get('reference_images',[])):raise ValueError('A chosen scene has a missing attached reference image. Reimport it or remove the attachment.')
            reference=references.get(n.get('reference_id'),{});interval=reference.get('source_interval',{})
            start,end=n.get('trim_start_s',interval.get('start_s',0)),n.get('trim_end_s',interval.get('end_s'))
            if not isinstance(start,(int,float)) or not math.isfinite(start) or start<0: raise ValueError('Reference trim start must be a finite non-negative time.')
            if end is not None and (not isinstance(end,(int,float)) or not math.isfinite(end) or end<=start): raise ValueError('Reference trim end must follow its start.')
            validate_reference_bounds(reference,start,end)
    return board

def brief(board):
    validate(board,True); full_path=board.get('chosen_path',board.get('order',[])); nodes={n['id']:n for n in board['nodes']}
    ids=[i for i in full_path if nodes[i].get('kind','scene')=='scene']
    refs={r['id']:r for r in catalog()['items']}; pairs={(e['from'],e['to']):e for e in board['edges']}
    scenes=[];elapsed=0
    for index,i in enumerate(ids):
        n=nodes[i];r=refs.get(n.get('reference_id'))
        scenes.append({'scene_id':n['scene_id'],'node':n,'reference':r,'start_s':elapsed,'end_s':elapsed+n['duration_s'],
                       'transition_to_next':pairs.get((i,ids[index+1])) if index+1<len(ids) else None,
                       'reference_images':[dict(refs[rid],policy='visual-reference-only') for rid in n.get('reference_images',[]) if rid in refs],
                       'effects':[e for e in board.get('effects',[]) if i in auxiliary_targets(e) and e.get('enabled',True)],
                       'feedback_cards':[e for e in board.get('feedback_cards',[]) if i in auxiliary_targets(e)]})
        elapsed+=n['duration_s']
    return {'board_id':board.get('board_id'),'board_title':board.get('title'),'board_revision':board.get('revision',0),
            'project_id':project()['id'],'asset_policy':'latest-approved','reference_policy':'visual-reference-only',
            'target_duration_s':board.get('target_duration_s'),'planned_duration_s':elapsed,'scenes':scenes,
            'production_approval':{'asset_policy':'latest-approved','model_version':project().get('approved_model_version'),'source_hash_policy':'actual_native_completion_bound_new_source_allowed'},
            'scope_markers':[nodes[i] for i in full_path if nodes[i].get('kind') in ('start','end')],
            'requires_camera_planning':True,'video_authorized':False}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
    def log_message(self,*args):pass
    def end_headers(self):
        if urlparse(self.path).path in ('/','/index.html','/app.js','/styles.css'):
            self.send_header('Cache-Control','no-store')
        super().end_headers()
    def send_head(self):
        if urlparse(self.path).path in ('/','/index.html','/app.js','/styles.css'):
            # The UI is refreshed independently of durable project assets.
            for key in ('If-Modified-Since','If-None-Match'):
                if key in self.headers:del self.headers[key]
        return super().send_head()
    def respond(self,value,status=200):
        raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
    def body(self):
        size=int(self.headers.get('Content-Length','0'))
        if size<1 or size>2*1024*1024: raise ValueError('JSON request is empty or too large.')
        return json.loads(self.rfile.read(size))
    def writable(self):
        origin=self.headers.get('Origin')
        if origin and origin!=f'http://{self.headers.get("Host")}':raise ValueError('Cross-origin writes are disabled.')
        if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
            raise ValueError('Use the local storyboard address.')
    def do_GET(self):
        route=urlparse(self.path).path
        query=parse_qs(urlparse(self.path).query);bid=query.get('board_id',[None])[0] or active_id()
        if route=='/api/boards':
            with LOCK:return self.respond({'items':board_items(),'active_id':active_id()})
        spec_match=re.fullmatch(r'/api/boards/([a-f0-9]{32})/spec',route)
        if spec_match:
            try:
                with LOCK:
                    selected=get_board(spec_match[1]);selected_id=selected['board_id']
                    legacy_id=active_state().get('legacy_board_id')
                    scene_requests=[item for path in sorted((DATA/'scene-requests').glob('*.json')) for item in [read(path)] if (item.get('board_id') or legacy_id)==selected_id]
                    production_requests=[item for path in sorted((DATA/'requests').glob('*.json')) for item in [read(path)] if (item.get('board_id') or legacy_id)==selected_id]
                    result=storyboard_reader.build_spec(selected,catalog(),scene_requests,production_requests,root=ROOT,project=project())
                    approval={'asset_policy':'latest-approved','model_version':project().get('approved_model_version')}
                    result['production_approval']=approval
                    result['brief']['production_approval']=approval
                    result['brief_sha256']=storyboard_reader.digest(result['brief'])
                    return self.respond(result)
            except ValueError as error:return self.respond({'error':str(error)},404)
        match=re.fullmatch(r'/api/boards/([a-f0-9]{32})',route)
        if match:
            try:return self.respond({'board':get_board(match[1])})
            except ValueError as e:return self.respond({'error':str(e)},404)
        if route=='/api/project':return self.respond(project())
        if route=='/api/catalog':return self.respond(catalog())
        if route=='/api/effects':return self.respond(effect_registry())
        if route=='/api/board':return self.respond(get_board())
        if route=='/api/snapshots':
            return self.respond({'board_id':bid,'items':[dict(id=p.stem,name=s['name'],created_utc=s['created_utc'],board_id=snapshot_board_id(s),board_revision=s.get('board_revision',s.get('board',{}).get('revision',0))) for p in sorted((DATA/'snapshots').glob('*.json'),reverse=True) for s in [read(p)] if snapshot_board_id(s)==bid]})
        if route=='/api/storyboard-requests':return self.respond({'board_id':bid,'items':[r for p in sorted((DATA/'requests').glob('*.json'),reverse=True) for r in [read(p)] if (r.get('board_id') or active_state().get('legacy_board_id'))==bid]})
        if route=='/api/scene-requests':return self.respond({'board_id':bid,'items':[r for p in sorted((DATA/'scene-requests').glob('*.json'),reverse=True) for r in [read(p)] if (r.get('board_id') or active_state().get('legacy_board_id'))==bid]})
        if route.startswith('/media/'):
            item=next((r for r in catalog()['items'] if r['id']==unquote(route[7:])),None)
            if not item or not item.get('video_source'):return self.send_error(404)
            return self.media(Path(item['video_source']))
        if re.fullmatch(r'/clip-media/[a-f0-9]{64}',route):return self.media(DATA/'clips'/(route.rsplit('/',1)[1]+'.mp4'))
        if route=='/' or route in ('/index.html','/app.js','/styles.css') or route.startswith('/assets/'):
            if route.startswith('/assets/'):
                candidate=(ROOT/unquote(route.lstrip('/'))).resolve()
                if not candidate.is_relative_to((ROOT/'assets').resolve()):return self.send_error(403)
            return super().do_GET()
        self.send_error(404)
    def media(self,path):
        if not path.is_file():return self.send_error(404)
        size=path.stat().st_size;start,end=0,size-1;value=self.headers.get('Range')
        if value:
            match=re.fullmatch(r'bytes=(\d+)-(\d*)',value)
            if not match:return self.send_error(416)
            start=int(match[1]);end=min(int(match[2]),end) if match[2] else end
            if start>end:return self.send_error(416)
        self.send_response(206 if value else 200);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'video/mp4')
        self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
        if value:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with path.open('rb') as f:
                f.seek(start);remaining=end-start+1
                while remaining:
                    chunk=f.read(min(65536,remaining))
                    if not chunk:break
                    self.wfile.write(chunk);remaining-=len(chunk)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_PUT(self):
        try:
            self.writable()
            if urlparse(self.path).path!='/api/board':return self.send_error(404)
            value=self.body()
            with LOCK:result=save_board(value)
            self.respond({'saved':True,'board_id':result['board_id'],'revision':result['revision'],'saved_utc':result['updated_utc'],'scene_codes':{n['scene_id']:n['scene_code'] for n in result['nodes'] if n.get('scene_code')},'scene_short_ids':{n['scene_id']:short_identity('S',n['scene_id']) for n in result['nodes'] if n.get('scene_id')}})
        except (ValueError,KeyError,TypeError) as e:self.respond({'error':str(e)},400)
    def do_PATCH(self):
        try:
            self.writable();route=urlparse(self.path).path
            if route=='/api/project':return self.respond({'project':rename_project(self.body())})
            match=re.fullmatch(r'/api/boards/([a-f0-9]{32})',route)
            if not match:return self.send_error(404)
            value=self.body();title=str(value.get('title','')).strip()[:150]
            if not title:raise ValueError('Add a storyboard name.')
            with LOCK:
                board=get_board(match[1]);board['title']=title;board=save_board(board)
            self.respond({'board':board})
        except (ValueError,KeyError,TypeError) as e:self.respond({'error':str(e)},400)
    def do_POST(self):
        try:
            self.writable();route=urlparse(self.path).path
            if route=='/api/import':return self.import_file()
            value=self.body()
            if route=='/api/clip-preview':return self.clip_preview(value)
            with LOCK:
                if route=='/api/clipboard':return self.respond(copy_local_identifier(value))
                production=re.fullmatch(r'/api/storyboard-requests/([A-Za-z0-9_-]+)/(receive|results)',route)
                if production:
                    path=DATA/'requests'/(production[1]+'.json');request=read(path)
                    if not request:raise ValueError('Storyboard request not found.')
                    if production[2]=='receive':
                        owner=str(value.get('owner','')).strip();note=str(value.get('note','')).strip()
                        if not owner or not note:raise ValueError('An explicit render owner must read and receive this snapshot.')
                        if request.get('received_by') and request['received_by']!=owner:raise ValueError('This request already belongs to another render owner.')
                        request.update(received_by=owner,received_utc=request.get('received_utc') or utc_now(),owner_note=note)
                        if request['status']!='actual_rendered_preview_published':request['status']='received_by_render_owner'
                        save(path,request);return self.respond({'request':request,'snapshot':read(DATA/'snapshots'/(request['snapshot_id']+'.json'))})
                    items,manifest_hash=render_return.prepare_result(value,request,ROOT)
                    if items is None:return self.respond({'request':request,'items':request.get('results',[]),'idempotent':True})
                    c=catalog();existing={x['id'] for x in c['items']}
                    if any(x['id'] in existing for x in items):raise ValueError('A prior returned version already uses this result identity; retain it and create a new request.')
                    c['items'].extend(items);save(ROOT/'catalog.json',c)
                    request.update(status='actual_rendered_preview_published',rendered_utc=utc_now(),result_manifest_sha256=manifest_hash,results=items,result={'count':len(items),'source_sha256':value.get('manifest',value)['source_sha256'],'actual_native_completion':True},user_board_automatically_modified=False)
                    save(path,request);return self.respond({'request':request,'items':items,'user_board_automatically_modified':False})
                received=re.fullmatch(r'/api/scene-requests/(scene-request-[a-f0-9]{32})/(receive|acknowledge)',route)
                if received:
                    path=DATA/'scene-requests'/(received[1]+'.json');request=read(path)
                    if not request:raise ValueError('Scene request not found.')
                    actor=str(value.get('actor','')).strip();note=str(value.get('note','')).strip()
                    if not actor or not note:raise ValueError('Add the receiving agent and its acknowledgement.')
                    request.update(status='received_by_codex' if received[2]=='receive' else 'acknowledged',received_utc=request.get('received_utc') or utc_now(),received_by=actor,acknowledgement=note)
                    if received[2]=='acknowledge':request['acknowledged_utc']=utc_now()
                    save(path,request);return self.respond({'request':request})
                if route=='/api/boards':
                    board=create_board(value);return self.respond({'board':board,'id':board['board_id']},201)
                match=re.fullmatch(r'/api/boards/([a-f0-9]{32})/activate',route)
                if match:return self.respond({'board':activate_board(match[1])})
                if route=='/api/scene-requests':
                    board=scoped_board(value)
                    kind=value.get('kind','new_scene')
                    if kind not in ('new_scene','scene_feedback'):raise ValueError('Unknown scene request type.')
                    title=str(value.get('title','New scene')).strip()[:150]
                    description=str(value.get('description','')).strip()
                    duration=float(value.get('duration_s',5))
                    if not title or not description or len(description)>12000:raise ValueError('Add a scene title and description below 12,000 characters.')
                    if not math.isfinite(duration) or duration<=0:raise ValueError('Use a positive scene duration.')
                    validate(board);snapshot=make_snapshot(board,'Scene request')
                    by_node={n['id']:n for n in board['nodes'] if n.get('kind','scene')=='scene'}
                    primary=by_node.get(value.get('node_id'),{})
                    scene_id=primary.get('scene_id') or value.get('scene_id') or ('scn_'+uuid.uuid4().hex if kind=='new_scene' else None)
                    if scene_id is not None and not re.fullmatch(r'scn_[a-f0-9]{32}',scene_id):raise ValueError('Invalid scene identity.')
                    scene_ids=[by_node[i]['scene_id'] for i in value.get('node_ids',[]) if i in by_node]
                    if not scene_ids and scene_id:scene_ids=[scene_id]
                    rid='scene-request-'+uuid.uuid4().hex
                    result={'board_id':board['board_id'],'board_title':board.get('title'),'board_revision':board.get('revision',0),'snapshot_id':snapshot['id'],
                            'id':rid,'title':title,'description':description,'duration_s':duration,'status':'queued_for_chat',
                            'created_utc':datetime.now(timezone.utc).isoformat(),'chat_thread_id':project().get('chat_thread_id'),
                            'project_id':project()['id'],'asset_policy':'latest-approved','renderer_started':False,'kind':kind,
                            'scene_id':scene_id,'scene_ids':scene_ids,'scene_code':scene_display_code(scene_id) if scene_id else None,'scene_codes':[scene_display_code(i) for i in scene_ids],'node_id':value.get('node_id'),'node_ids':value.get('node_ids',[]),'reference_id':value.get('reference_id')}
                    references={r['id']:r for r in catalog()['items']}
                    if any(rid not in references for rid in primary.get('reference_images',[])):raise ValueError('A scene has a missing attached reference image. Reimport it or remove the attachment.')
                    result['reference_images']=[dict(references[rid],policy='visual-reference-only') for rid in primary.get('reference_images',[]) if rid in references]
                    source=DATA/'scene-requests'/f'{rid}.json';save(source,result)
                    if kind=='scene_feedback':return self.respond({'request':result,'item':None,'message':'Feedback queued for the Codex chat.'},201)
                    item={'id':rid,'title':title,'version':'New scene','orientation':'horizontal','status':'needs_preview',
                          'status_reason':'Description saved; no scene frames have been rendered.','tags':['new-scene','draft'],
                          'notes':description,'description':description,'source':str(source),'frames':{},'image':None,
                          'source_interval':{'start_s':0,'end_s':duration},'geometry_policy':'latest-approved',
                          'sha256':hashlib.sha256(description.encode()).hexdigest()}
                    c=catalog();c['items'].append(item);save(ROOT/'catalog.json',c)
                    return self.respond({'request':result,'item':item,'message':'Queued for the Codex chat; delivery is confirmed separately.'},201)
                if route=='/api/snapshots':
                    board=scoped_board(value);validate(board)
                    return self.respond(make_snapshot(board,value.get('name','Untitled revision')))
                match=re.fullmatch('/api/snapshots/([A-Za-z0-9_-]+)/restore',route)
                if match:
                    snapshot=read(DATA/'snapshots'/f'{match[1]}.json')
                    if not snapshot:raise ValueError('Snapshot not found.')
                    bid=value.get('board_id') or active_id()
                    if snapshot_board_id(snapshot)!=bid:raise ValueError('Snapshot belongs to another storyboard.')
                    board=save_board(dict(snapshot['board'],board_id=bid))
                    return self.respond({'board':board,'restored':True})
                if route=='/api/storyboard-requests':
                    board=scoped_board(value);plan=brief(board);snapshot=make_snapshot(board,'Storyboard request')
                    rid=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8]
                    result={'id':rid,'board_id':board['board_id'],'board_title':board.get('title'),
                            'board_revision':board.get('revision',0),'snapshot_id':snapshot['id'],
                            'status':'requested','created_utc':utc_now(),'brief':plan,'results':[],
                            'message':'Saved for the Codex render owner. No video or Unreal job started automatically.'}
                    save(DATA/'requests'/f'{rid}.json',result);return self.respond(result,201)
            self.send_error(404)
        except subprocess.TimeoutExpired:self.respond({'error':'Clip preview timed out; original media is preserved. Retry when rendering is idle.'},408)
        except (ValueError,KeyError,TypeError,OSError,subprocess.CalledProcessError) as e:self.respond({'error':str(e)},400)
    def clip_preview(self,value):
        item=next((r for r in catalog()['items'] if r['id']==value.get('reference_id')),None)
        if not item or not item.get('video_source'):raise ValueError('This reference has no source clip.')
        source=Path(item['video_source']);interval=item['source_interval']
        start=float(value.get('start_s',interval['start_s']));end=float(value.get('end_s',interval['end_s']))
        if not math.isfinite(start) or not math.isfinite(end) or start<0 or end<=start or end-start>600:raise ValueError('Choose a valid clip interval of at most 10 minutes.')
        validate_reference_bounds(item,start,end)
        probe=json.loads(subprocess.check_output([media_tool('ffprobe'),'-v','error','-show_format','-of','json',str(source)]))
        full_duration=float(probe['format']['duration'])
        if end>full_duration+.05:raise ValueError('Clip endpoint exceeds the source duration.')
        key=hashlib.sha256(f'{source}:{source.stat().st_mtime_ns}:{source.stat().st_size}:{start:.9f}:{end:.9f}:v1'.encode()).hexdigest()
        folder=DATA/'clips';folder.mkdir(exist_ok=True);output=folder/(key+'.mp4')
        with CLIP_LOCK:
            if not output.exists():
                temp=folder/(key+'.tmp.mp4')
                subprocess.run([media_tool('ffmpeg'),'-v','error','-ss',str(start),'-i',str(source),'-t',str(end-start),
                    '-map','0:v:0','-map','0:a:0?','-vf',"scale=w='min(640,iw)':h=-2",'-c:v','libx264','-threads','2',
                    '-preset','ultrafast','-crf','22','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart','-y',str(temp)],check=True,timeout=120)
                temp.replace(output)
        actual=json.loads(subprocess.check_output([media_tool('ffprobe'),'-v','error','-show_format','-show_streams','-of','json',str(output)]))
        video_duration=float(next(s for s in actual['streams'] if s['codec_type']=='video').get('duration',end-start))
        self.respond({'url':'/clip-media/'+key,'start_s':0,'end_s':min(end-start,video_duration),
                      'source_start_s':start,'source_end_s':end,'source_preserved':True,'physically_trimmed':True})
    def import_file(self):
        match=re.search(r'boundary="?([^";]+)',self.headers.get('Content-Type',''))
        total=int(self.headers.get('Content-Length','0'))
        if not match or total>1024*1024*1024:raise ValueError('Choose one image or video below 1 GiB.')
        boundary=match[1].encode();first=self.rfile.readline(65536)
        if first.strip()!=b'--'+boundary:raise ValueError('Invalid file upload.')
        headers=b''
        while True:
            line=self.rfile.readline(65536)
            if line in (b'\r\n',b'\n',b''):break
            headers+=line
            if len(headers)>65536:raise ValueError('Invalid file headers.')
        name=re.search(br'filename="([^"]+)"',headers)
        if not name:raise ValueError('Choose a file.')
        original=Path(name[1].decode(errors='replace')).name;ext=Path(original).suffix.lower()
        if ext not in ('.png','.jpg','.jpeg','.webp','.mp4','.mov','.m4v'):raise ValueError('Supported files: PNG, JPEG, WebP, MP4, MOV.')
        uid='import-'+uuid.uuid4().hex;intake=DATA/'imports';intake.mkdir(parents=True,exist_ok=True)
        file=intake/(uid+ext);delimiter=b'\r\n--'+boundary;remaining=total-len(first)-len(headers)-2;buffer=b''
        with file.open('wb') as out:
            while remaining>0:
                chunk=self.rfile.read(min(65536,remaining));remaining-=len(chunk);buffer+=chunk
                found=buffer.find(delimiter)
                if found>=0:out.write(buffer[:found]);break
                retain=len(delimiter)+8
                if len(buffer)>retain:out.write(buffer[:-retain]);buffer=buffer[-retain:]
            else:raise ValueError('Incomplete file upload; original retained for recovery.')
        probe=json.loads(subprocess.check_output([media_tool('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',str(file)]))
        video=next((s for s in probe['streams'] if s['codec_type']=='video'),None)
        if not video:raise ValueError('This file has no image or video stream.')
        isvideo=ext in ('.mp4','.mov','.m4v');duration=float(probe.get('format',{}).get('duration',1)) if isvideo else 1
        frames={}
        (ROOT/'assets').mkdir(parents=True,exist_ok=True)
        for key,t in [('start',0),('middle',duration/2),('end',max(0,duration-0.1))]:
            dest=ROOT/'assets'/f'{uid}_{key}.png'
            command=[media_tool('ffmpeg'),'-v','error']
            if isvideo:command+=['-ss',str(t)]
            command+=['-i',str(file),'-frames:v','1','-vf','scale=640:-1','-y',str(dest)]
            subprocess.run(command,check=True)
            if not dest.is_file():raise ValueError('A requested preview frame could not be decoded. Original file retained.')
            frames[key]='/assets/'+dest.name
        original_hash=hashlib.sha256()
        with file.open('rb') as original_file:
            for chunk in iter(lambda:original_file.read(1024*1024),b''):original_hash.update(chunk)
        digest=original_hash.hexdigest()
        item={'id':uid,'title':original,'version':'User import','orientation':'vertical' if video['height']>video['width'] else 'horizontal',
              'status':'user_reference','tags':['import'],'notes':'Local reference; native scene source is unmapped.'+(' Single image: all three preview slots show the same source.' if not isvideo else ''),'source':str(file),'sha256':digest,
              'frames':frames,'image':frames['middle'],'source_interval':{'start_s':0,'end_s':duration},'fps':video.get('avg_frame_rate','1/1'),
              'geometry_policy':'visual_reference_only; render uses latest approved assets'}
        if isvideo:item.update(video='/media/'+uid,video_source=str(file))
        with LOCK:
            c=catalog();c['items'].append(item);save(ROOT/'catalog.json',c)
        self.respond({'item':item},201)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--port',type=int,default=8840);ap.add_argument('--project',type=Path);ap.add_argument('--alias-port',type=int,action='append',default=[]);args=ap.parse_args()
    if args.project:ROOT=args.project.resolve();DATA=ROOT/'data'
    DATA.mkdir(parents=True,exist_ok=True)
    initialize_board_store()
    for alias in args.alias_port:
        auxiliary=ThreadingHTTPServer(('127.0.0.1',alias),Handler)
        threading.Thread(target=auxiliary.serve_forever,daemon=True).start()
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
