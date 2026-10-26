"""Temporary-project checks; never reads or writes the live studio data."""
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('studio_server', Path(__file__).parents[1] / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class BoardStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        server.ROOT = Path(self.temp.name)
        server.DATA = server.ROOT / 'data'
        self.original = {'title': 'Original', 'asset_policy': 'latest-approved', 'target_duration_s': 203.6,
                         'nodes': [{'id': 'scene', 'duration_s': 5, 'reference_id': 'ref', 'x': 0, 'y': 0}],
                         'edges': [], 'effects': [], 'chosen_path': ['scene'], 'notes': 'Preserve me',
                         'extra': {'unknown': [1, 2]}}
        server.save(server.DATA / 'board.json', self.original)
        server.save(server.ROOT / 'project.json', {'id': 'test-project','approved_model_version':'0b'})
        server.save(server.ROOT / 'catalog.json', {'items': [{'id': 'ref'}]})
        server.save(server.DATA / 'snapshots' / 'legacy.json', {'name': 'Legacy', 'created_utc': 'old', 'board': self.original})
        server.initialize_board_store()
        self.initial = server.active_id()
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def test_future_schema_is_rejected_without_store_mutation(self):
        board=self.request('/api/board');original=server.board_file(board['board_id']).read_bytes()
        for version in (99,'1',True):
            candidate=dict(board,schema_version=version)
            with self.assertRaisesRegex(ValueError,'Unsupported storyboard schema'):server.save_board(candidate)
            self.assertEqual(server.board_file(board['board_id']).read_bytes(),original)
        future=server.DATA/'snapshots/future.json';server.save(future,{'board':dict(board,schema_version=99)})
        before=future.read_bytes()
        with self.assertRaisesRegex(ValueError,'Unsupported storyboard schema'):server.initialize_board_store()
        self.assertEqual(future.read_bytes(),before)
        self.assertEqual(server.board_file(board['board_id']).read_bytes(),original)

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, method='GET', value=None):
        data = json.dumps(value).encode() if value is not None else None
        req = Request(f'http://127.0.0.1:{self.http.server_port}{path}', data=data, method=method,
                      headers={'Content-Type': 'application/json'})
        with urlopen(req) as response:
            return json.load(response)

    def test_lossless_migration_and_idempotent_restart(self):
        migrated = self.request('/api/board')
        for key, value in self.original.items():
            self.assertEqual([{k:v for k,v in n.items() if k not in ('scene_id','scene_code','short_id')} for n in migrated[key]], value) if key=='nodes' else self.assertEqual(migrated[key], value)
        self.assertEqual(server.read(server.DATA / 'board.pre-store.json'), self.original)
        server.initialize_board_store()
        self.assertEqual(server.active_id(), self.initial)
        self.assertEqual(len(self.request('/api/boards')['items']), 1)

    def test_create_switch_duplicate_rename_and_scoped_autosave(self):
        new = self.request('/api/boards', 'POST', {'title': 'Blank'})['board']
        bid = new['board_id']
        self.assertEqual(new['nodes'], [])
        self.assertEqual(new['effects'], [])
        self.assertNotIn('target_duration_s', new)
        self.assertEqual(self.request('/api/boards')['active_id'], self.initial)
        self.request(f'/api/boards/{bid}/activate', 'POST', {})
        old = server.get_board(self.initial)
        old['notes'] = 'Saved by another client'
        result = self.request('/api/board', 'PUT', old)
        self.assertEqual(result['board_id'], self.initial)
        self.assertEqual(self.request('/api/board')['board_id'], bid)
        self.assertEqual(server.read(server.DATA / 'board.json')['board_id'], bid)
        self.assertEqual(server.get_board(self.initial)['notes'], old['notes'])
        duplicate = self.request('/api/boards', 'POST', {'title': 'Copy', 'duplicate_from': self.initial})['board']
        self.assertEqual(duplicate['nodes'][0]['id'], old['nodes'][0]['id'])
        self.assertNotEqual(duplicate['nodes'][0]['scene_id'], old['nodes'][0]['scene_id'])
        self.assertEqual(duplicate['nodes'][0]['source_scene_id'], old['nodes'][0]['scene_id'])
        self.assertEqual(duplicate['source_board_id'], self.initial)
        self.assertEqual(duplicate['revision'], 0)
        renamed = self.request(f'/api/boards/{duplicate["board_id"]}', 'PATCH', {'title': 'Renamed'})['board']
        self.assertEqual(renamed['title'], 'Renamed')
        self.assertEqual(self.request(f'/api/boards/{duplicate["board_id"]}')['board'], renamed)
        self.assertEqual(len(self.request('/api/boards')['items']), 3)

    def test_snapshot_scope_legacy_and_restore(self):
        snap = self.request('/api/snapshots', 'POST', {'board_id': self.initial, 'name': 'Saved'})
        new = self.request('/api/boards', 'POST', {'title': 'Other'})['board']
        self.request(f'/api/boards/{new["board_id"]}/activate', 'POST', {})
        self.assertEqual(self.request('/api/snapshots')['items'], [])
        self.assertEqual(len(self.request(f'/api/snapshots?board_id={self.initial}')['items']), 2)
        with self.assertRaises(HTTPError) as failure:
            self.request(f'/api/snapshots/{snap["id"]}/restore', 'POST', {})
        self.assertEqual(failure.exception.code, 400)
        restored = self.request('/api/snapshots/legacy/restore', 'POST', {'board_id': self.initial})['board']
        self.assertEqual(restored['board_id'], self.initial)
        self.assertEqual(restored['notes'], self.original['notes'])
        self.assertEqual(server.active_id(), new['board_id'])

    def test_request_context_and_scope(self):
        result = self.request('/api/storyboard-requests', 'POST', {'board_id': self.initial})
        self.assertEqual(result['board_id'], self.initial)
        self.assertEqual(result['brief']['board_id'], self.initial)
        self.assertEqual(result['brief']['planned_duration_s'], 5)
        self.assertTrue((server.DATA / 'snapshots' / f'{result["snapshot_id"]}.json').exists())
        scene = self.request('/api/scene-requests', 'POST', {'board_id': self.initial, 'kind': 'scene_feedback',
                                                        'title': 'Fix', 'description': 'Adjust camera'})['request']
        self.assertEqual(scene['board_title'], 'Original')
        new = self.request('/api/boards', 'POST', {'title': 'Other'})['board']
        self.request(f'/api/boards/{new["board_id"]}/activate', 'POST', {})
        self.assertEqual(self.request('/api/storyboard-requests')['items'], [])
        self.assertEqual(len(self.request(f'/api/scene-requests?board_id={self.initial}')['items']), 1)

    def test_stable_scene_migration_autosave_and_snapshot_identity(self):
        initial=server.get_board()
        scene_id=initial['nodes'][0]['scene_id']
        self.assertRegex(scene_id,r'^scn_[a-f0-9]{32}$')
        server.initialize_board_store()
        self.assertEqual(server.get_board()['nodes'][0]['scene_id'],scene_id)
        value=dict(initial,nodes=[dict(initial['nodes'][0])])
        value['nodes'][0].pop('scene_id')
        self.request('/api/board','PUT',value)
        self.assertEqual(server.get_board()['nodes'][0]['scene_id'],scene_id)
        snap=self.request('/api/snapshots','POST',{'board_id':self.initial})
        value=server.get_board();value['nodes'][0]['title']='New title'
        self.request('/api/board','PUT',value)
        restored=self.request('/api/snapshots/'+snap['id']+'/restore','POST',{'board_id':self.initial})['board']
        self.assertEqual(restored['nodes'][0]['scene_id'],scene_id)
        legacy=self.request('/api/snapshots/legacy/restore','POST',{'board_id':self.initial})['board']
        self.assertEqual(legacy['nodes'][0]['scene_id'],scene_id)
        request=self.request('/api/scene-requests','POST',{'board_id':self.initial,'node_id':'scene',
                            'node_ids':['scene'],'kind':'scene_feedback','title':'Change','description':'Camera fix'})['request']
        self.assertEqual(request['scene_id'],scene_id)
        self.assertEqual(request['scene_ids'],[scene_id])
        duplicate=dict(restored,nodes=[restored['nodes'][0],dict(restored['nodes'][0],id='second')])
        with self.assertRaises(HTTPError):self.request('/api/board','PUT',duplicate)

    def test_compact_identity_project_unique_snapshot_and_ack(self):
        initial=server.get_board();n=initial['nodes'][0]
        self.assertEqual(n['scene_code'],'S1')
        snap=self.request('/api/snapshots','POST',{'board_id':self.initial})
        copy=self.request('/api/boards','POST',{'title':'Copy','duplicate_from':self.initial})['board']
        self.assertNotEqual(copy['nodes'][0]['scene_code'],n['scene_code'])
        self.assertEqual(copy['nodes'][0]['source_scene_id'],n['scene_id'])
        restored=self.request('/api/snapshots/'+snap['id']+'/restore','POST',{'board_id':self.initial})['board']
        self.assertEqual(restored['nodes'][0]['scene_code'],n['scene_code'])
        server.initialize_board_store();self.assertEqual(server.get_board()['nodes'][0]['scene_code'],'S1')
        req=self.request('/api/scene-requests','POST',{'board_id':self.initial,'node_id':'scene','kind':'scene_feedback','title':'Fix','description':'Keep the cassette in frame'})['request']
        self.assertEqual(req['scene_code'],'S1')
        received=self.request('/api/scene-requests/'+req['id']+'/receive','POST',{'actor':'Codex','note':'Description received in active chat'})['request']
        self.assertEqual(received['status'],'received_by_codex')
        ack=self.request('/api/scene-requests/'+req['id']+'/acknowledge','POST',{'actor':'Codex','note':'Understood; camera request retained for render owner'})['request']
        self.assertEqual(ack['status'],'acknowledged');self.assertFalse(ack['renderer_started'])
        with self.assertRaises(HTTPError):self.request('/api/scene-requests/'+req['id']+'/receive','POST',{})

    def test_render_handoff_blocks_missing_cycles_branches_and_bad_markers(self):
        base=server.get_board();first=base['nodes'][0]
        def blocked(board):
            with self.assertRaises(HTTPError):self.request('/api/storyboard-requests','POST',{'board_id':self.initial,'board':board})
        value=json.loads(json.dumps(base));value['nodes'][0]['reference_id']='missing';blocked(value)
        value=json.loads(json.dumps(base));second=dict(first,id='second',scene_id='scn_'+'1'*32);value['nodes'].append(second)
        value['edges']=[{'id':'out','from':'scene','to':'second','transition':'cut'},{'id':'back','from':'second','to':'scene','transition':'continuous'}];blocked(value)
        value['edges']=[{'id':'out','from':'scene','to':'second','transition':'cut'}];value['render_path_ends_here']=False;blocked(value)
        value['nodes'].append({'id':'start','kind':'start','duration_s':0,'x':0,'y':0});value['edges']=[{'id':'wrong','from':'scene','to':'start','transition':'cut'}];blocked(value)
        value=json.loads(json.dumps(base));value['effects']=[{'id':'fx','kind':'lens_flare','parent_node_id':'scene','preset_id':'uninstalled','settings':{'intensity':1}}];blocked(value)
        value=json.loads(json.dumps(base));value['chosen_path']=['missing'];blocked(value)
        self.assertEqual(server.get_board(),base)

    def test_reference_clip_bounds_block_before_media_decode(self):
        server.save(server.ROOT/'catalog.json',{'items':[{'id':'ref','video_source':'/not/read/or/decoded.mp4','source_interval':{'start_s':82.7,'end_s':90.13333333333334}}]})
        for start,end in [(0,203.6),(82.6,90),(83,90.2)]:
            with self.assertRaises(HTTPError) as failure:self.request('/api/clip-preview','POST',{'reference_id':'ref','start_s':start,'end_s':end})
            self.assertEqual(failure.exception.code,400)
        board=server.get_board();board['nodes'][0].update(trim_start_s=0,trim_end_s=203.6)
        with self.assertRaises(HTTPError):self.request('/api/storyboard-requests','POST',{'board_id':self.initial,'board':board})
        server.validate_reference_bounds({'source_interval':{'start_s':82.7,'end_s':90.13333333333334}},82.7,90.13333333333334)

    def test_end_marker_cut_port_invariant(self):
        board=server.get_board();board['nodes'].append({'id':'end','kind':'end','duration_s':0,'x':240,'y':0})
        board['edges']=[{'id':'finish','from':'scene','to':'end','transition':'continuous'}]
        with self.assertRaises(HTTPError):self.request('/api/board','PUT',board)
        board['edges'][0]['transition']='cut';self.request('/api/board','PUT',board)
        self.assertEqual(server.get_board()['edges'][0]['transition'],'cut')

    def test_native_return_requires_owner_real_pngs_source_identity_and_preserves_board(self):
        import hashlib,struct,zlib
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
        server.save(server.ROOT/'catalog.json',{'items':[{'id':'ref','picture_source_sha256':'b'*64,'tags':['latest-model-0a'],'source_interval':{'start_s':0,'end_s':5}}]})
        request=self.request('/api/storyboard-requests','POST',{'board_id':self.initial});rid=request['id'];original=server.get_board()
        frames={}
        for i,phase in enumerate(('start','middle','end')):
            path=server.ROOT/(phase+'.png');path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(bytes([0,i,0,0])))+chunk(b'IEND',b''))
            frames[phase]={'path':str(path),'sha256':sha(path)}
        native_source=server.ROOT/'scene.blend';native_source.write_bytes(b'isolated native source fixture');source_hash=sha(native_source)
        receipt=server.ROOT/'completion.json';receipt_data={'status':'ACTUAL_NATIVE_RENDER_COMPLETE','native_jobs_terminal_exit0':True,'actual_frame_count':3,'request_id':rid,'brief_sha256':server.storyboard_reader.digest(request['brief']),'source_sha256':source_hash,'model_version':'0b','frames':list(frames.values()),'scene_frames':{original['nodes'][0]['scene_id']:frames}};server.save(receipt,receipt_data)
        manifest={'schema_version':1,'request_id':rid,'owner':'native-test','asset_policy':'latest-approved','source_sha256':source_hash,'native_source':{'path':str(native_source),'sha256':source_hash},'model_version':'0b','completion_receipt':{'path':str(receipt),'sha256':sha(receipt)},'results':[{'node_id':'scene','scene_id':original['nodes'][0]['scene_id'],'title':'Actual fixture','version':'TEST ONLY','quality_label':'Isolated API PNG fixture, not a real native render','frames':frames}]}
        with self.assertRaises(HTTPError):self.request('/api/storyboard-requests/'+rid+'/results','POST',{'manifest':manifest})
        self.request('/api/storyboard-requests/'+rid+'/receive','POST',{'owner':'native-test','note':'Read immutable single-scene fixture'})
        bad=json.loads(json.dumps(manifest));bad['results'][0]['scene_id']='scn_'+'b'*32
        with self.assertRaises(HTTPError):self.request('/api/storyboard-requests/'+rid+'/results','POST',{'manifest':bad})
        bad=json.loads(json.dumps(manifest));bad['model_version']='0a'
        with self.assertRaises(HTTPError):self.request('/api/storyboard-requests/'+rid+'/results','POST',{'manifest':bad})
        bad=json.loads(json.dumps(manifest));bad['results'][0]['frames']['start']['sha256']='0'*64
        with self.assertRaises(HTTPError):self.request('/api/storyboard-requests/'+rid+'/results','POST',{'manifest':bad})
        self.assertEqual(len(self.request('/api/catalog')['items']),1)
        result=self.request('/api/storyboard-requests/'+rid+'/results','POST',{'manifest':manifest})
        self.assertEqual(result['request']['status'],'actual_rendered_preview_published');self.assertFalse(result['user_board_automatically_modified'])
        self.assertEqual(server.get_board(),original);self.assertEqual(len(result['items']),1)
        for phase,url in result['items'][0]['frames'].items():self.assertTrue((server.ROOT/url.lstrip('/')).is_file())
        again=self.request('/api/storyboard-requests/'+rid+'/results','POST',{'manifest':manifest});self.assertTrue(again['idempotent']);self.assertEqual(len(self.request('/api/catalog')['items']),2)
        invalid=server.ROOT/'invalid.png';invalid.write_text('Saved source is not an image')
        with self.assertRaises(ValueError):server.render_return.actual_png(invalid)

    def test_archived_fixture_snapshot_startup_does_not_resurrect_board(self):
        other=self.request('/api/boards','POST',{'title':'Archive fixture'})['board'];bid=other['board_id']
        self.request('/api/snapshots','POST',{'board_id':bid,'name':'Archive evidence'})
        archive=server.DATA/'archived-boards'/bid;archive.mkdir(parents=True)
        server.board_file(bid).replace(archive/(bid+'.json'))
        server.initialize_board_store()
        self.assertEqual(server.active_id(),self.initial)
        self.assertFalse(server.board_file(bid).exists())
        self.assertEqual(len(self.request('/api/boards')['items']),1)

    def test_validation_does_not_mutate_other_board(self):
        before = server.get_board()
        invalid = dict(before, nodes=[{'id': 'bad', 'duration_s': 0}])
        with self.assertRaises(HTTPError):
            self.request('/api/board', 'PUT', invalid)
        self.assertEqual(server.get_board(), before)
        with self.assertRaises(ValueError):
            server.get_board('../board')


if __name__ == '__main__':
    unittest.main()
