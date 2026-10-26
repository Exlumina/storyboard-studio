import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server

class ShortIdentityTests(unittest.TestCase):
    def test_stable_unique_compact_and_original_aliases(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'DATA',Path(folder)):
            a=server.short_identity('S','uuid-a');b=server.short_identity('S','uuid-b');r=server.short_identity('R','uuid-a')
            self.assertEqual(a,server.short_identity('S','uuid-a'));self.assertEqual(len(a),6);self.assertEqual(len(b),6);self.assertEqual(len(r),6);self.assertEqual(len({a,b,r}),3)
            board={'revision':4,'nodes':[{'id':'node','scene_id':'uuid-a','scene_code':'S8','duration_s':3}],'edges':[],'chosen_path':['node']}
            decorated=server.board_short_identities(board)
            self.assertEqual(decorated['nodes'][0]['short_id'],a);self.assertEqual(decorated['nodes'][0]['scene_code'],'S8');self.assertEqual(board['nodes'][0]['scene_id'],'uuid-a');self.assertNotIn('short_id',board['nodes'][0]);self.assertEqual(decorated['revision'],4)
    def test_collision_is_resolved_and_never_reused(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'DATA',Path(folder)):
            code=server.short_identity('S','first')
            registry=json.loads((Path(folder)/'short-identities.json').read_text())
            registry['codes']={'S:reserved':code};(Path(folder)/'short-identities.json').write_text(json.dumps(registry))
            second=server.short_identity('S','first');self.assertNotEqual(second,code);self.assertEqual(second,server.short_identity('S','first'))
    def test_duplicate_gets_new_identity_short_label(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'DATA',Path(folder)):
            original=server.board_short_identities(server.ensure_scene_ids({'nodes':[{'id':'n','scene_id':'scn_'+'a'*32}]}))
            duplicate=server.ensure_scene_ids(original,duplicate=True)
            self.assertNotEqual(original['nodes'][0]['short_id'],duplicate['nodes'][0]['short_id']);self.assertEqual(duplicate['nodes'][0]['source_scene_id'],original['nodes'][0]['scene_id'])

if __name__=='__main__':unittest.main()
