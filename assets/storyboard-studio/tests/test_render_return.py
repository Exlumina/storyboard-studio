"""Synthetic admission checks; fixtures do not establish native rendering."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
import render_return
from storyboard_conformance import digest

class ReturnContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source.blend';self.source.write_bytes(b'synthetic native source')
        source_hash=self.sha(self.source)
        self.request={'id':'request-test','status':'received_by_render_owner','received_by':'native-owner','brief':{'asset_policy':'latest-approved','production_approval':{'asset_policy':'latest-approved','model_version':'generic-v1'},'scenes':[{'scene_id':'scene-test','node':{'id':'node-test','duration_s':2,'description':'Draft intent'},'reference':None,'effects':[]}]}}
        frames={}
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        for i,phase in enumerate(('start','middle','end')):
            path=self.root/(phase+'.png');path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(bytes([0,i,0,0])))+chunk(b'IEND',b''));frames[phase]={'path':str(path),'sha256':self.sha(path)}
        self.receipt={'status':'ACTUAL_NATIVE_RENDER_COMPLETE','native_jobs_terminal_exit0':True,'request_id':self.request['id'],'brief_sha256':digest(self.request['brief']),'actual_frame_count':3,'source_sha256':source_hash,'model_version':'generic-v1','frames':list(frames.values()),'scene_frames':{'scene-test':frames}}
        self.receipt_path=self.root/'receipt.json'
        self.manifest={'schema_version':1,'request_id':self.request['id'],'owner':'native-owner','asset_policy':'latest-approved','source_sha256':source_hash,'native_source':{'path':str(self.source),'sha256':source_hash},'model_version':'generic-v1','results':[{'node_id':'node-test','scene_id':'scene-test','version':'TEST ONLY','quality_label':'Synthetic fixture','frames':frames}]}
        self.bind_receipt()
    def tearDown(self):self.temp.cleanup()
    @staticmethod
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    def bind_receipt(self):
        self.receipt_path.write_text(json.dumps(self.receipt));self.manifest['completion_receipt']={'path':str(self.receipt_path),'sha256':self.sha(self.receipt_path)}
    def test_draft_return_has_verified_source_and_request_provenance(self):
        self.request['brief']['scenes'][0]['reference']={'source_interval':{'start_s':100,'end_s':150}}
        self.receipt['brief_sha256']=digest(self.request['brief']);self.bind_receipt()
        items,_=render_return.prepare_result(self.manifest,self.request,self.root)
        self.assertEqual(items[0]['reference_source_interval'],{'start_s':100,'end_s':150})
        self.assertEqual(items[0]['native_source'],str(self.source.resolve()))
        self.assertEqual(items[0]['brief_sha256'],digest(self.request['brief']))
        self.assertEqual(items[0]['source_interval'],{'start_s':0,'end_s':2})
    def test_wrong_frozen_receipt_and_changed_native_source_reject(self):
        for field in ('request_id','brief_sha256'):
            original=self.receipt[field];self.receipt[field]='wrong';self.bind_receipt()
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'frozen request'):render_return.prepare_result(self.manifest,self.request,self.root)
            self.receipt[field]=original
        self.bind_receipt();self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'missing or changed'):render_return.prepare_result(self.manifest,self.request,self.root)
    def test_swapped_preview_phases_reject(self):
        frames=self.manifest['results'][0]['frames']=copy.deepcopy(self.manifest['results'][0]['frames'])
        frames['start'],frames['end']=frames['end'],frames['start']
        with self.assertRaisesRegex(ValueError,'exact scene'):render_return.prepare_result(self.manifest,self.request,self.root)
    def test_missing_requested_scene_rejects(self):
        self.request['brief']['scenes'].append({'scene_id':'other','node':{'id':'other','duration_s':1},'reference':None,'effects':[]})
        self.receipt['brief_sha256']=digest(self.request['brief']);self.bind_receipt()
        with self.assertRaisesRegex(ValueError,'every scene'):render_return.prepare_result(self.manifest,self.request,self.root)
    def test_effect_binding_cannot_be_omitted_or_borrowed(self):
        effect={'id':'fx','kind':'lens_flare','preset_id':'generic','enabled':True,'settings':{'intensity':1}}
        self.request['brief']['scenes'][0]['effects']=[effect];self.receipt['brief_sha256']=digest(self.request['brief']);self.bind_receipt()
        with self.assertRaisesRegex(ValueError,'effect bindings'):render_return.prepare_result(self.manifest,self.request,self.root)
        bindings=[{k:effect[k] for k in ('kind','preset_id','enabled','settings')}];self.manifest['results'][0]['rendered_effect_bindings']=bindings
        with self.assertRaisesRegex(ValueError,'native completion receipt'):render_return.prepare_result(self.manifest,self.request,self.root)
        self.receipt['rendered_effect_bindings_by_scene']={'scene-test':bindings};self.bind_receipt()
        self.assertEqual(len(render_return.prepare_result(self.manifest,self.request,self.root)[0]),1)
    def test_corrupt_published_copy_is_not_silently_reused(self):
        items,manifest_hash=render_return.prepare_result(self.manifest,self.request,self.root)
        self.request['result_manifest_sha256']=manifest_hash
        path=self.root/items[0]['frames']['start'].lstrip('/');path.write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError,'previously published'):render_return.prepare_result(self.manifest,self.request,self.root)

if __name__=='__main__':unittest.main()
