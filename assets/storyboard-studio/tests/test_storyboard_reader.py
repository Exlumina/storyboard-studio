import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import storyboard_reader as reader

class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.board={'board_id':'a'*32,'revision':3,'title':'Test','target_duration_s':5,'render_path_ends_here':True,'chosen_path':['start','a','b','end'],'nodes':[{'id':'start','kind':'start'},{'id':'a','scene_id':'unique-a','scene_code':'S1','reference_id':'ref','reference_images':['image'],'duration_s':2,'description':'Close hardware'},{'id':'b','duration_s':3,'description':'Second view'},{'id':'end','kind':'end'},{'id':'alt','duration_s':8}], 'edges':[{'id':'1','from':'start','to':'a','transition':'cut'},{'id':'2','from':'a','to':'b','transition':'continuous'},{'id':'3','from':'b','to':'end','transition':'cut'}], 'effects':[{'id':'fx','target_node_ids':['a','b'],'type':'flare'}],'feedback_cards':[{'id':'note','target_node_ids':['a'],'description':'Center subject'}]}
    def test_complete_reader_and_latest_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            image=Path(directory)/'ref.png';image.write_bytes(b'pixels')
            catalog={'items':[{'id':'ref','source':str(image),'frames':{'middle':str(image)}},{'id':'image','source':str(image)}]}
            requests=[{'id':'old','node_ids':['a'],'created_utc':'1','description':'Old'},{'id':'new','node_ids':['a'],'created_utc':'2','description':'New'}]
            value=reader.build_spec(self.board,catalog,requests,[],Path(directory))
            self.assertFalse(value['validation']['errors'])
            self.assertEqual(value['brief']['scenes'][0]['scene_id'],'unique-a')
            self.assertEqual(value['brief']['scenes'][1]['start_s'],2)
            self.assertEqual(value['brief']['scenes'][0]['transition_to_next']['transition'],'continuous')
            self.assertEqual(value['brief']['scenes'][0]['latest_feedback_request']['id'],'new')
            self.assertEqual(value['alternatives'][0]['node']['id'],'alt')
            self.assertEqual(len(value['brief']['scenes'][0]['effects']),1)
            self.assertEqual(len(value['brief']['scenes'][0]['feedback_cards']),1)
            self.assertFalse(value['user_execute']);self.assertFalse(value['renderer_started'])
    def test_missing_cycle_duration_block(self):
        b=copy.deepcopy(self.board);b['edges'].append({'from':'b','to':'a','transition':'cut'});b['target_duration_s']=10
        value=reader.build_spec(b,{'items':[{'id':'ref','source':'/missing-ref.png'}]},[],[])
        errors=' '.join(value['validation']['errors'])
        self.assertIn('cycle',errors);self.assertIn('missing attached',errors);self.assertIn('missing_or_unhydrated',errors);self.assertIn('target',errors)
    def test_blank_card_blocks_execution(self):
        b=copy.deepcopy(self.board);b['nodes'][2].pop('description')
        result=reader.build_spec(b,{'items':[]},[],[])
        self.assertIn('describe this scene', ' '.join(result['validation']['errors']))

    def test_disconnected_graph_and_feedback_are_excluded(self):
        b=copy.deepcopy(self.board)
        b['nodes'][1].pop('reference_id');b['nodes'][1].pop('reference_images')
        b['edges'].append({'from':'alt','to':'alt','transition':'cut'})
        b['feedback_cards'].append({'id':'ignored','target_node_ids':['alt'],'text':'Ignore this'})
        b['effects'].append({'id':'ignored-fx','target_node_ids':['alt']})
        b['target_duration_s']=203.6
        result=reader.build_spec(b,{'items':[]},[],[],follow_path_duration=True)
        self.assertFalse(result['validation']['errors'])
        self.assertEqual(result['brief']['planned_duration_s'],5)
        self.assertEqual([x['id'] for x in result['brief']['feedback_cards']],['note'])
        self.assertEqual([x['id'] for x in result['brief']['effects']],['fx'])
        self.assertTrue(result['validation']['warnings'])

    def test_project_approval_frozen_and_invalid_target_blocks(self):
        b=copy.deepcopy(self.board);b['nodes'][1].pop('reference_id');b['nodes'][1].pop('reference_images')
        value=reader.build_spec(b,{'items':[]},[],[],project={'approved_model_version':'approved-generic'})
        self.assertEqual(value['brief']['production_approval']['model_version'],'approved-generic')
        for target in ('invalid',float('nan'),float('inf'),-1):
            b['target_duration_s']=target
            with self.subTest(target=target):
                self.assertIn('Target duration must', ' '.join(reader.build_spec(b,{'items':[]},[],[])['validation']['errors']))

    def test_modern_project_requires_explicit_scope(self):
        b=copy.deepcopy(self.board);b['chosen_path']=['a','b'];b['render_path_ends_here']=True
        value=reader.build_spec(b,{'items':[]},[],[],project={'marker_supported':True})
        self.assertIn('Start-to-End',' '.join(value['validation']['errors']))

    def test_marker_only_path_blocks(self):
        b=copy.deepcopy(self.board);b['chosen_path']=['start','end'];b['edges']=[{'from':'start','to':'end','transition':'cut'}]
        self.assertIn('at least one scene',' '.join(reader.build_spec(b,{'items':[]},[],[])['validation']['errors']))

    def test_unsupported_schema_and_blocked_snapshot_do_not_issue_execution(self):
        board=copy.deepcopy(self.board);board['schema_version']=99
        result=reader.build_spec(board,{'items':[]},[],[])
        self.assertIn('Unsupported storyboard schema', ' '.join(result['validation']['errors']))
        board=copy.deepcopy(self.board);board['nodes'][2].pop('description')
        def fetch(base,route,payload=None):
            if route.startswith('/api/boards/'):return {'board':board}
            if route=='/api/board':return board
            if route=='/api/snapshots':return {'id':'blocked-review','board':payload['board']}
            return {'items':[]}
        with patch.object(reader,'fetch',fetch):result=reader.read('http://127.0.0.1:8840',snapshot_name='Blocked review',execute_authorized=True)
        self.assertTrue(result['validation']['errors'])
        self.assertNotIn('execution_request',result)
        self.assertIn('Resolve validation',result['execution_request_withheld'])

    def test_loopback_only(self):
        for base in ['https://127.0.0.1:4402','http://example.com','http://127.0.0.1:8840/foo','http://user:pass@localhost:4402']:
            with self.assertRaises(ValueError):reader.local_base(base)
    def test_concurrent_board_edit_refused(self):
        board=copy.deepcopy(self.board); calls=[]
        def fetch(base,route,payload=None):
            if route.startswith('/api/boards/'):
                calls.append(route)
                return {'board':dict(board,revision=3 if len(calls)==1 else 4)}
            return {'items':[]}
        with patch.object(reader,'fetch',fetch):
            with self.assertRaisesRegex(ValueError,'changed while reading'):
                reader.read('http://127.0.0.1:8840','a'*32)

    def test_snapshot_does_not_call_render(self):
        board=copy.deepcopy(self.board);board['nodes'][1].pop('reference_id');board['nodes'][1].pop('reference_images')
        calls=[]
        def fetch(base,route,payload=None):
            calls.append(route)
            if route.startswith('/api/boards/'):return {'board':board}
            if route=='/api/board':return board
            if route=='/api/catalog':return {'items':[]}
            if route=='/api/snapshots':return {'id':'snap','board':payload['board']}
            return {'items':[]}
        with patch.object(reader,'fetch',fetch):value=reader.read('http://127.0.0.1:8840','a'*32,'Review',True)
        self.assertTrue(value['user_execute']);self.assertEqual(value['execution_request']['snapshot_id'],'snap');self.assertFalse(value['renderer_started'])
        self.assertEqual(calls.count('/api/snapshots'),1)
        self.assertFalse(any('/render' in r for r in calls))

if __name__=='__main__':unittest.main()
