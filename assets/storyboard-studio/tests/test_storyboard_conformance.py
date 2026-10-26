import copy
import unittest
from storyboard_conformance import contract, validate


class ConformanceTests(unittest.TestCase):
    def setUp(self):
        self.request = {'id': 'r', 'board_id': 'b', 'brief': {'scenes': [
            {'scene_id': 'one', 'node': {'id': 'a', 'duration_s': 5, 'reference_id': 'old'}, 'transition_to_next': {'transition': 'continuous'}},
            {'scene_id': 'two', 'node': {'id': 'b', 'duration_s': 3, 'reference_id': 'new'}, 'transition_to_next': None}]}}
        self.mapping = contract(self.request)
        t = 0
        for s in self.mapping['scenes']:
            s.update(output_start_s=t, output_end_s=t+s['duration_s'], render_job_id='native')
            t += s['duration_s']

    def test_bound_mapping(self):
        self.assertFalse(validate(self.request, self.mapping)['errors'])

    def test_malformed_mapping_and_declared_duration_block(self):
        for candidate in (None, [], {'scenes':None}, {'scenes':[None]}):
            with self.subTest(candidate=candidate):self.assertTrue(validate(self.request,candidate)['errors'])
        candidate=copy.deepcopy(self.mapping);candidate['scenes'][0]['duration_s']=50
        self.assertTrue(validate(self.request,candidate)['errors'])

    def test_unrelated_manual_plan(self):
        self.assertTrue(validate(self.request, {'jobs': []})['errors'])

    def test_reorder_extra_missing_retime_and_transition(self):
        for mutation in ('reorder', 'extra', 'missing', 'retime', 'transition', 'intent', 'hash'):
            c = copy.deepcopy(self.mapping)
            if mutation == 'reorder': c['scenes'].reverse()
            if mutation == 'extra': c['scenes'].append(c['scenes'][0])
            if mutation == 'missing': c['scenes'].pop()
            if mutation == 'retime': c['scenes'][0]['output_end_s'] = 6
            if mutation == 'transition': c['scenes'][0]['transition_to_next'] = {'transition': 'cut'}
            if mutation == 'intent': c['scenes'][0]['intent_sha256'] = 'wrong'
            if mutation == 'hash': c['brief_sha256'] = 'wrong'
            with self.subTest(mutation=mutation):
                self.assertTrue(validate(self.request, c)['errors'])

    def test_explicit_feedback_and_effect_bindings(self):
        request = copy.deepcopy(self.request)
        request['brief']['scenes'][0].update(
            feedback_cards=[{'id':'center','text':'Keep rocket centered'}],
            effects=[{'id':'flare','kind':'lens_flare','preset_id':'VintageBlue',
                      'enabled':True,'settings':{'intensity':1}}])
        mapping = contract(request)
        t = 0
        for scene in mapping['scenes']:
            scene.update(output_start_s=t,output_end_s=t+scene['duration_s'],render_job_id='native')
            t += scene['duration_s']
        self.assertFalse(validate(request,mapping)['errors'])
        for mutation in ('shift_feedback','omit_feedback','wrong_preset','preview_gain','disabled'):
            changed = copy.deepcopy(mapping)
            scene = changed['scenes'][0]
            if mutation == 'shift_feedback':
                changed['scenes'][1]['feedback_card_ids'] = scene['feedback_card_ids']
                scene['feedback_card_ids'] = []
            if mutation == 'omit_feedback': scene.pop('feedback_card_ids')
            if mutation == 'wrong_preset': scene['effect_bindings'][0]['preset_id'] = 'Different'
            if mutation == 'preview_gain': scene['effect_bindings'][0]['settings']['intensity'] = 100
            if mutation == 'disabled': scene['effect_bindings'][0]['enabled'] = False
            with self.subTest(mutation=mutation):
                self.assertTrue(validate(request,changed)['errors'])


if __name__ == "__main__":
    unittest.main()
