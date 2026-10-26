"""Attachment persistence and render handoff checks in disposable local projects."""
import unittest
import hashlib
import json
import struct
import zlib
import subprocess
import shutil
from pathlib import Path
from urllib.request import Request, urlopen
import test_board_store as store_tests
server=store_tests.server

class SceneImageTests(unittest.TestCase):
    def setUp(self):
        self.store=store_tests.BoardStoreTests()
        self.store.setUp()
        server.save(server.ROOT/'catalog.json',{'items':[{'id':'ref'}, {'id':'external-image','title':'Film still.png','source':'/local/imports/original.png','sha256':'original-sha','frames':{'start':'/assets/still.png'},'version':'User import','geometry_policy':'visual_reference_only'}]})
        self.board=self.store.request('/api/board')
        self.board['nodes'][0]['reference_images']=['external-image']
        self.store.request('/api/board','PUT',self.board)
    def tearDown(self):self.store.tearDown()
    def test_persistence_brief_and_request_provenance(self):
        board=self.store.request('/api/board')
        self.assertEqual(board['nodes'][0]['reference_images'],['external-image'])
        brief=server.brief(board)
        attachment=brief['scenes'][0]['reference_images'][0]
        self.assertEqual(attachment['source'],'/local/imports/original.png')
        self.assertEqual(attachment['sha256'],'original-sha')
        self.assertEqual(attachment['policy'],'visual-reference-only')
        request=self.store.request('/api/scene-requests','POST',{'board_id':board['board_id'],'board':board,'node_id':'scene','kind':'scene_feedback','title':'Scene','description':'Use attached screenshot composition','duration_s':5})['request']
        self.assertEqual(request['reference_images'][0]['sha256'],'original-sha')
    def test_missing_image_blocks_production(self):
        self.board['nodes'][0]['reference_images']=['missing']
        with self.assertRaisesRegex(ValueError,'missing attached reference image'):server.validate(self.board,rendering=True)
    @staticmethod
    def fixture_png():
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\xff\0\0\0\xff\0'*2))+chunk(b'IEND',b'')
    def test_image_import_creates_asset_directory_and_retains_original(self):
        original=self.fixture_png()
        boundary='local-reference-test-boundary'
        payload=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="Screenshot.png"\r\nContent-Type: image/png\r\n\r\n'.encode()+original+f'\r\n--{boundary}--\r\n'.encode())
        request=Request(f'http://127.0.0.1:{self.store.http.server_port}/api/import',data=payload,headers={'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
        with urlopen(request) as response:imported=json.load(response)['item']
        self.assertEqual(imported['sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(Path(imported['source']).read_bytes(),original)
        self.assertTrue((server.ROOT/'assets').is_dir())
        self.assertTrue(all((server.ROOT/url.lstrip('/')).is_file() for url in imported['frames'].values()))
    def test_jpeg_screenshot_import_does_not_seek_static_image(self):
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:self.skipTest('ffmpeg unavailable for synthetic JPEG fixture')
        screenshot=server.ROOT/'synthetic-fixture.jpg';png=server.ROOT/'synthetic-fixture.png';png.write_bytes(self.fixture_png())
        subprocess.run([ffmpeg,'-v','error','-i',str(png),'-frames:v','1',str(screenshot)],check=True,capture_output=True)
        original=screenshot.read_bytes()
        boundary='local-jpeg-test-boundary'
        payload=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="Film_screenshot.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()+original+f'\r\n--{boundary}--\r\n'.encode())
        request=Request(f'http://127.0.0.1:{self.store.http.server_port}/api/import',data=payload,headers={'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
        with urlopen(request) as response:imported=json.load(response)['item']
        self.assertEqual(imported['sha256'],hashlib.sha256(original).hexdigest())
        self.assertTrue(all((server.ROOT/url.lstrip('/')).is_file() for url in imported['frames'].values()))
    def test_media_tools_resolve_path_and_fail_actionably(self):
        from unittest.mock import patch
        with patch.object(server.shutil,'which',return_value='/portable/bin/ffmpeg'):
            self.assertEqual(server.media_tool('ffmpeg'),'/portable/bin/ffmpeg')
        with patch.object(server.shutil,'which',return_value=None):
            with self.assertRaisesRegex(ValueError,'Install FFmpeg'):server.media_tool('ffprobe')
    def test_attachment_structure(self):
        self.board['nodes'][0]['reference_images']='invalid'
        with self.assertRaisesRegex(ValueError,'reference IDs'):server.validate(self.board)

if __name__=='__main__':unittest.main()
