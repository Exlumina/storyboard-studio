"""Read an exact local board for Codex; freeze without launching any renderer."""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import urlparse, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

def local_base(value):
    u = urlparse(value)
    if u.scheme != 'http' or u.hostname not in ('127.0.0.1', 'localhost', '::1') or u.username or u.password or u.query or u.fragment or u.path not in ('', '/'):
        raise ValueError('Use a loopback-only HTTP Storyboard Studio address.')
    return value.rstrip('/')

def fetch(base, route, payload=None):
    request = Request(base + route, data=None if payload is None else json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=15) as response:
        return json.load(response)

def asset_check(value, root):
    if not value:
        return {'value': value, 'status': 'not_supplied'}
    if value.startswith('/') and not value.startswith(('/assets/', '/data/')):
        path = Path(value)
    elif value.startswith(('/assets/', '/data/')):
        path = root / value.lstrip('/')
    else:
        return {'value': value, 'status': 'not_local_file', 'reason': 'A media URL is not filesystem evidence; inspect its catalog source.'}
    try:
        if not path.is_file():
            return {'value': value, 'path': str(path), 'status': 'missing_or_unhydrated'}
        with path.open('rb') as stream:
            stream.read(1)
        return {'value': value, 'path': str(path), 'status': 'locally_readable', 'bytes': path.stat().st_size}
    except OSError as error:
        return {'value': value, 'path': str(path), 'status': 'unreadable_or_unhydrated', 'error': str(error)}

def reference_record(ref, root):
    if ref is None:
        return None
    result = dict(ref)
    result['asset_checks'] = [asset_check(v, root) for v in dict.fromkeys([ref.get('source'), ref.get('video_source'), ref.get('image'), *ref.get('frames', {}).values()]) if v]
    result['policy'] = 'visual-reference-only; latest approved geometry for production'
    return result

def build_spec(board, catalog, requests, production_requests, root=ROOT, execute_authorized=False, follow_path_duration=False, project=None):
    project = project or {}
    refs = {r['id']: r for r in catalog.get('items', [])}
    nodes = {n['id']: n for n in board.get('nodes', [])}
    path = board.get('chosen_path', [])
    edges = board.get('edges', [])
    errors = []
    version=board.get('schema_version',1)
    if type(version) is not int or version!=1:errors.append('Unsupported storyboard schema version. Preserve the board and use a compatible Studio version.')
    warnings = []
    if len(nodes) != len(board.get('nodes', [])): errors.append('Duplicate node IDs.')
    if not path: errors.append('Choose a connected path before execution.')
    if path and not any(nodes.get(i, {}).get('kind', 'scene') == 'scene' for i in path): errors.append('Connect at least one scene before execution.')
    if project.get('marker_supported') and path:
        if nodes.get(path[0], {}).get('kind') != 'start' or nodes.get(path[-1], {}).get('kind') != 'end':errors.append('Connect an explicit Start-to-End chosen path before execution.')
        if any(nodes.get(i, {}).get('kind', 'scene') != 'scene' for i in path[1:-1]):errors.append('Start and End must bound the scene sequence, not interrupt it.')
    if len(set(path)) != len(path): errors.append('Chosen path repeats a node or contains a cycle.')
    if any(i not in nodes for i in path): errors.append('Chosen path contains missing nodes.')
    outgoing = {}
    for edge in edges:
        if edge.get('from') not in path or edge.get('to') not in path: continue
        if edge.get('from') not in nodes or edge.get('to') not in nodes: errors.append('Connection has a missing endpoint: ' + str(edge.get('id')))
        outgoing.setdefault(edge.get('from'), []).append(edge)
    visiting, visited = set(), set()
    def visit(i):
        if i in visiting: return True
        if i in visited: return False
        visiting.add(i)
        cycle = any(visit(e['to']) for e in outgoing.get(i, []) if e.get('to') in nodes)
        visiting.remove(i); visited.add(i)
        return cycle
    if any(visit(i) for i in path if i in nodes): errors.append('Graph contains a cycle. Disconnect it before execution.')
    for a, b in zip(path, path[1:]):
        matched = [e for e in outgoing.get(a, []) if e.get('to') == b]
        if len(matched) != 1: errors.append(f'Chosen connection {a} to {b} is missing or ambiguous.')
        elif matched[0].get('transition') not in ('cut', 'continuous'): errors.append(f'Choose Cut or Continuous on {a} to {b}.')
    latest = {}
    for req in sorted(requests, key=lambda r: r.get('created_utc', '')):
        ids = req.get('node_ids') or ([req['node_id']] if req.get('node_id') else [])
        for i in ids: latest[i] = req
    effects = board.get('effects', [])
    feedback = board.get('feedback_cards', [])
    def targets(card): return card.get('auxiliary_targets') or card.get('targets') or card.get('target_node_ids') or card.get('node_ids') or ([card['parent_node_id']] if card.get('parent_node_id') else [])
    elapsed = 0
    scenes = []
    def scene(n, selected):
        nonlocal elapsed
        rid = n.get('reference_id'); ref = reference_record(refs.get(rid), root)
        images = [reference_record(refs.get(i), root) or {'id': i, 'missing': True} for i in n.get('reference_images', [])]
        if selected and rid and ref is None: errors.append(f'{n["id"]}: missing reference {rid}.')
        if selected:
            if n.get('kind', 'scene') not in ('start', 'end') and not (ref or images or str(n.get('description') or n.get('requested_changes') or '').strip()):
                errors.append(f'{n["id"]}: describe this scene or attach a visual reference before execution.')
            for attached in images:
                if attached.get('missing'): errors.append(f'{n["id"]}: missing attached image {attached["id"]}.')
            for media in [ref, *images]:
                if media:
                    for check in media.get('asset_checks', []):
                        if check['status'] in ('missing_or_unhydrated', 'unreadable_or_unhydrated'): errors.append(f'{n["id"]}: {check["status"]}: {check.get("path")}.')
        result = {'node': dict(n), 'scene_id': n.get('scene_id') or n['id'], 'scene_code': n.get('scene_code'), 'reference': ref, 'reference_images': images, 'latest_feedback_request': latest.get(n['id']), 'effects': [e for e in effects if n['id'] in targets(e)], 'feedback_cards': [f for f in feedback if n['id'] in targets(f)]}
        if selected:
            index = path.index(n['id']); nextid = path[index+1] if index+1 < len(path) else None
            result['transition_to_next'] = next((e for e in outgoing.get(n['id'], []) if e.get('to') == nextid), None)
            if n.get('kind', 'scene') not in ('start', 'end'):
                try: duration = float(n.get('duration_s', 0))
                except (ValueError, TypeError): duration = 0
                if not math.isfinite(duration) or duration <= 0: errors.append(n['id'] + ': set a positive finite duration.'); duration = 0
                result.update(start_s=elapsed, end_s=elapsed+duration); elapsed += duration
        return result
    ordered = [scene(nodes[i], True) for i in path if i in nodes]
    scenes = [s for s in ordered if s['node'].get('kind', 'scene') not in ('start', 'end')]
    target = board.get('target_duration_s')
    try: target_number = None if target is None else float(target)
    except (ValueError, TypeError): target_number = float('nan')
    if target_number is not None and (not math.isfinite(target_number) or target_number <= 0):
        errors.append('Target duration must be a positive finite number.'); target_number = None
    if target_number is not None and abs(target_number-elapsed) > 1e-6:
        message = f'Chosen views total {elapsed:g}s but target is {target}s.'
        if follow_path_duration: warnings.append(message + ' Explicit execution follows connected scene durations without stretching.')
        else: errors.append(message + ' Resolve durations explicitly.')
    if path and path[-1] in nodes and nodes[path[-1]].get('kind') != 'end' and not board.get('render_path_ends_here'): errors.append('Set an End card or explicitly mark the chosen path end.')
    alternatives = [scene(n, False) for i,n in nodes.items() if i not in path]
    brief = {'board_id': board.get('board_id'), 'board_revision': board.get('revision'), 'board_title': board.get('title'), 'project_id': board.get('project_id'), 'board_sha256': digest(board), 'chosen_path': path, 'target_duration_s': target, 'planned_duration_s': elapsed, 'asset_policy': 'latest-approved', 'reference_policy': 'visual-reference-only', 'scenes': scenes, 'scope_markers': [s['node'] for s in ordered if s['node'].get('kind') in ('start','end')], 'effects': [e for e in effects if set(targets(e)) & set(path)], 'feedback_cards': [f for f in feedback if set(targets(f)) & set(path)], 'duration_policy': 'connected-scene-durations' if follow_path_duration else 'target-required', 'production_approval': {'asset_policy':'latest-approved', 'model_version':project.get('approved_model_version'), 'source_hash_policy':'actual_native_completion_bound_new_source_allowed'}, 'video_authorized': bool(execute_authorized)}
    return {'schema':'STORYBOARD_READER_V1', 'board': board, 'board_sha256':digest(board), 'brief':brief, 'brief_sha256':digest(brief), 'ordered_cards':ordered, 'alternatives':alternatives, 'latest_feedback_requests':list({r['id']:r for r in latest.values()}.values()), 'production_requests':production_requests, 'validation':{'status':'BLOCKED' if errors else 'READY_FOR_EXPLICIT_CHAT_INSTRUCTION','errors':list(dict.fromkeys(errors)), 'warnings':warnings}, 'user_execute':bool(execute_authorized), 'renderer_started':False}

def read(base, board_id=None, snapshot_name=None, execute_authorized=False, follow_path_duration=False):
    base = local_base(base)
    if board_id and not re.fullmatch(r'[a-f0-9]{32}', board_id): raise ValueError('Use the full local board ID.')
    board = fetch(base, '/api/boards/'+board_id)['board'] if board_id else fetch(base, '/api/board')
    query = '?' + urlencode({'board_id':board['board_id']})
    catalog = fetch(base, '/api/catalog')
    project = fetch(base, '/api/project')
    requests = fetch(base, '/api/scene-requests'+query).get('items', [])
    production = fetch(base, '/api/storyboard-requests'+query).get('items', [])
    after = fetch(base, '/api/boards/'+board['board_id'])['board']
    if digest(after) != digest(board): raise ValueError('Board changed while reading. Save edits and read again; no execution spec was issued.')
    result = build_spec(board,catalog,requests,production,execute_authorized=execute_authorized, follow_path_duration=follow_path_duration, project=project)
    if snapshot_name:
        frozen = fetch(base,'/api/snapshots',{'board_id':board['board_id'],'board':board,'name':snapshot_name})
        if digest(frozen['board']) != result['board_sha256']: raise ValueError('Snapshot board differs from the board read. Read it again.')
        result['snapshot_id'] = frozen['id']; result['brief']['snapshot_id'] = frozen['id']; result['brief_sha256'] = digest(result['brief'])
        if not result['validation']['errors']:
            result['execution_request'] = {'id':'reader-'+frozen['id'],'board_id':board['board_id'],'board_revision':board.get('revision'),'snapshot_id':frozen['id'],'brief':result['brief']}
        else:
            result['execution_request_withheld'] = 'Resolve validation errors and freeze a new request.'
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',default='http://127.0.0.1:8840')
    parser.add_argument('--board');parser.add_argument('--snapshot',metavar='NAME')
    parser.add_argument('--execute-authorized',action='store_true',help='Record explicit human chat authorization only; never starts render.')
    parser.add_argument('--follow-path-duration',action='store_true',help='Explicitly follow connected scene durations; report legacy duration target as a warning.')
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    try: value=read(args.base,args.board,args.snapshot,args.execute_authorized,args.follow_path_duration)
    except (ValueError, OSError) as error:
        parser.exit(2, str(error)+'\n')
    raw=json.dumps(value,indent=2)+'\n'
    if args.out: args.out.write_text(raw)
    else: print(raw,end='')
    return 2 if value['validation']['errors'] else 0

if __name__=='__main__':raise SystemExit(main())
