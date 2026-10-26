"""Validate a declared render mapping against its immutable storyboard request.
This checks production planning, never visual/camera conformance of rendered pixels.
"""
import argparse
import hashlib
import json
import math


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def contract(request):
    brief = request['brief']
    scenes = []
    for s in brief['scenes']:
        n = s.get('node', s)
        if n.get('kind') in ('start', 'end'):
            continue
        scenes.append({'scene_id': s.get('scene_id') or n.get('scene_id') or n['id'],
                       'reference_id': n.get('reference_id'),
                       'duration_s': n['duration_s'],
                       'transition_to_next': s.get('transition_to_next'),
                       'intent_sha256': digest(s),
                       'feedback_card_ids': sorted(f['id'] for f in s.get('feedback_cards', [])),
                       'effect_bindings': [{k:e.get(k) for k in ('id','kind','preset_id','enabled','settings')} for e in s.get('effects', [])]})
    return {'request_id': request['id'], 'board_id': request.get('board_id') or brief.get('board_id') or brief.get('project_id'),
            'brief_sha256': digest(brief), 'scenes': scenes}


def validate(request, candidate):
    expected = contract(request)
    errors = []
    if not isinstance(candidate, dict):return {'status':'BLOCK_RENDER_PLAN','errors':['Render mapping must be an object.'],'planned_duration_s':0,'scope':'Declared mapping only.'}
    for field in ('request_id', 'board_id', 'brief_sha256'):
        if candidate.get(field) != expected[field]:
            errors.append(f'{field} must match the immutable storyboard request.')
    actual = candidate.get('scenes', [])
    if not isinstance(actual,list) or any(not isinstance(s,dict) for s in actual):
        errors.append('Render mapping scenes must be a list of scene objects.'); actual=[]
    if [s.get('scene_id') for s in actual] != [s['scene_id'] for s in expected['scenes']]:
        errors.append('Scene IDs and order differ: missing, extra, duplicated or reordered scenes.')
    t = 0
    for i, (want, got) in enumerate(zip(expected['scenes'], actual)):
        label = f'Scene {i + 1} ({want["scene_id"]})'
        for field in ('reference_id', 'duration_s', 'intent_sha256', 'transition_to_next', 'feedback_card_ids', 'effect_bindings'):
            if got.get(field) != want[field]:
                errors.append(f'{label}: {field} differs from storyboard.')
        duration = float(want['duration_s'])
        for field, value in [('output_start_s', t), ('output_end_s', t + duration)]:
            try:
                valid = math.isclose(float(got[field]), value, rel_tol=0, abs_tol=1e-6)
            except (KeyError, ValueError, TypeError):
                valid = False
            if not valid:
                errors.append(f'{label}: {field} must be {value}; silent retiming is prohibited.')
        if not got.get('render_job_id'):
            errors.append(f'{label}: missing native render job binding.')
        t += duration
    return {'status': 'PASS_DECLARED_STORYBOARD_MAPPING' if not errors else 'BLOCK_RENDER_PLAN',
            'errors': errors, 'planned_duration_s': sum(float(s['duration_s']) for s in expected['scenes']),
            'scope': 'Declared mapping only. Actual camera, animation and pixels still require review.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request', required=True)
    p.add_argument('--mapping')
    args = p.parse_args()
    with open(args.request) as f:
        request = json.load(f)
    if args.mapping:
        with open(args.mapping) as f:
            result = validate(request, json.load(f))
        print(json.dumps(result, indent=2))
        raise SystemExit(bool(result['errors']))
    print(json.dumps(contract(request), indent=2))


if __name__ == '__main__':
    main()
