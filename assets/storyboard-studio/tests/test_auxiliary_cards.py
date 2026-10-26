"""Multi-scene auxiliary planning inputs, disposable loopback project only."""
import unittest
import test_board_store as store_tests
server=store_tests.server
class AuxiliaryTests(unittest.TestCase):
    def setUp(self):
        self.store=store_tests.BoardStoreTests();self.store.setUp()
        server.save(server.ROOT/'effects.json',{'effects':[{'id':'lens_flare','presets':[{'id':'installed'}]}]})
        self.board=self.store.request('/api/board');first=self.board['nodes'][0]
        self.board['nodes'].append({**first,'id':'other','scene_id':'scn_'+'f'*32})
        self.board['chosen_path']=['scene','other'];self.board['edges']=[{'id':'link','from':'scene','to':'other','transition':'cut'}]
        self.board['effects']=[{'id':'fx','kind':'lens_flare','parent_node_id':'scene','target_node_ids':['scene','other'],'preset_id':'installed','settings':{'intensity':1},'x':0,'y':-100}]
        self.board['feedback_cards']=[{'id':'feedback','kind':'feedback','title':'Camera','text':'Engine visible','target_node_ids':['scene','other'],'x':0,'y':200}]
    def tearDown(self):self.store.tearDown()
    def test_roundtrip_and_both_scene_briefs(self):
        self.store.request('/api/board','PUT',self.board)
        saved=self.store.request('/api/board')
        self.assertEqual(saved['feedback_cards'],self.board['feedback_cards'])
        brief=server.brief(saved)
        for scene in brief['scenes']:
            self.assertEqual(scene['effects'][0]['id'],'fx')
            self.assertEqual(scene['feedback_cards'][0]['text'],'Engine visible')
    def test_orphan_cards_allowed_but_invalid_target_rejected(self):
        self.board['effects'][0]['target_node_ids']=[]
        self.board['feedback_cards'][0]['target_node_ids']=[]
        server.validate(self.board,rendering=True)
        self.board['feedback_cards'][0]['target_node_ids']=['missing']
        with self.assertRaisesRegex(ValueError,'existing scene'):server.validate(self.board)
    def test_duplicate_target_rejected(self):
        self.board['effects'][0]['target_node_ids']=['scene','scene']
        with self.assertRaisesRegex(ValueError,'unique scene'):server.validate(self.board)
if __name__=='__main__':unittest.main()
