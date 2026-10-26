"""Read-only explicit board spec endpoint with current saved feedback."""
import unittest
import test_board_store as store_tests
class BoardSpecTests(unittest.TestCase):
    def setUp(self):self.store=store_tests.BoardStoreTests();self.store.setUp()
    def tearDown(self):self.store.tearDown()
    def test_explicit_board_never_uses_or_changes_active_board(self):
        original=self.store.request('/api/board')
        original['nodes'][0]['requested_changes']='Keep spacecraft centered'
        original['feedback_cards']=[{'id':'feedback1','kind':'feedback','text':'Show mechanism','x':0,'y':200,'target_node_ids':['scene']}]
        self.store.request('/api/board','PUT',original)
        other=self.store.request('/api/boards','POST',{'title':'Other'})['board']
        self.store.request('/api/boards/'+other['board_id']+'/activate','POST',{})
        spec=self.store.request('/api/boards/'+original['board_id']+'/spec')
        self.assertEqual(spec['board']['board_id'],original['board_id'])
        self.assertEqual(spec['board']['nodes'][0]['requested_changes'],'Keep spacecraft centered')
        self.assertEqual(spec['brief']['feedback_cards'][0]['text'],'Show mechanism')
        self.assertEqual(spec['production_approval']['model_version'],'0b')
        self.assertFalse(spec['renderer_started'])
        self.assertFalse(spec['user_execute'])
        self.assertEqual(self.store.request('/api/boards')['active_id'],other['board_id'])
    def test_modern_request_requires_start_and_end(self):
        server=store_tests.server
        config=server.project();config['marker_supported']=True;server.save(server.ROOT/'project.json',config)
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError):self.store.request('/api/storyboard-requests','POST',{'board_id':self.store.initial})
        board=self.store.request('/api/board')
        board['nodes'].extend([{'id':'start','kind':'start','duration_s':0,'x':-240,'y':0},{'id':'end','kind':'end','duration_s':0,'x':240,'y':0}])
        board['chosen_path']=['start','scene','end'];board['edges']=[{'id':'enter','from':'start','to':'scene','transition':'cut'},{'id':'finish','from':'scene','to':'end','transition':'cut'}]
        self.store.request('/api/board','PUT',board)
        self.assertEqual(len(self.store.request('/api/storyboard-requests','POST',{'board_id':self.store.initial})['brief']['scenes']),1)

    def test_ui_refresh_ignores_stale_conditional_cache(self):
        from urllib.request import Request, urlopen
        from pathlib import Path
        root=self.store.temp.name
        path=Path(root)/'app.js';path.write_text('first version')
        url=f'http://127.0.0.1:{self.store.http.server_port}/app.js'
        with urlopen(url) as response:
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            modified=response.headers['Last-Modified']
        path.write_text('new version')
        with urlopen(Request(url,headers={'If-Modified-Since':modified})) as response:
            self.assertEqual(response.status,200)
            self.assertEqual(response.read(),b'new version')
            self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_described_draft_and_disconnected_cycle_request(self):
        board=self.store.request('/api/board');board['nodes'][0].pop('reference_id');board['nodes'][0]['description']='A new generic camera view'
        board['nodes'].extend([{'id':'alt-a','duration_s':2,'x':0,'y':200},{'id':'alt-b','duration_s':2,'x':240,'y':200}])
        board['edges']=[{'id':'alt-1','from':'alt-a','to':'alt-b','transition':'cut'},{'id':'alt-2','from':'alt-b','to':'alt-a','transition':'cut'}]
        self.store.request('/api/board','PUT',board)
        result=self.store.request('/api/storyboard-requests','POST',{'board_id':board['board_id']})
        self.assertEqual([s['node']['id'] for s in result['brief']['scenes']],['scene'])
        self.assertIsNone(result['brief']['scenes'][0]['reference'])
        self.assertEqual(result['brief']['production_approval']['model_version'],'0b')

if __name__=='__main__':unittest.main()
