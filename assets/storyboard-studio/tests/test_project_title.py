"""Project-title API checks against disposable stores and ephemeral HTTP ports."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('project_title_server',Path(__file__).parents[1]/'server.py')
server=importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ProjectTitleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        server.ROOT=Path(self.temp.name);server.DATA=server.ROOT/'data'
        self.original={'id':'immutable-project','title':'Original project','approved_model_version':'0b',
                       'marker_supported':True,'unknown':{'retain':[1,2]},'chat_thread_id':'thread-id'}
        server.save(server.ROOT/'project.json',self.original)
        self.bytes=(server.ROOT/'project.json').read_bytes()
        server.save(server.DATA/'board.json',{'title':'Independent board','asset_policy':'latest-approved','nodes':[],'edges':[],'effects':[]})
        server.initialize_board_store()
        self.board=server.get_board()
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();self.temp.cleanup()

    def request(self,path='/api/project',value=None,method='PATCH'):
        data=json.dumps(value).encode() if value is not None else None
        req=Request(f'http://127.0.0.1:{self.http.server_port}{path}',data=data,method=method,
                    headers={'Content-Type':'application/json'})
        with urlopen(req) as response:return json.load(response)

    def backups(self):return list((server.DATA/'config-backups').glob('*.json'))

    def test_persisted_rename_preserves_configuration_identity_and_board(self):
        result=self.request(value={'title':'  Renamed project  '})['project']
        expected=dict(self.original,title='Renamed project')
        self.assertEqual(result,expected)
        self.assertEqual(server.read(server.ROOT/'project.json'),expected)
        self.assertEqual(self.request(method='GET'),expected)
        self.assertEqual(server.get_board(),self.board)
        self.assertEqual(len(self.backups()),1)
        self.assertEqual(self.backups()[0].read_bytes(),self.bytes)

    def test_invalid_or_identifier_changes_leave_config_and_backups_untouched(self):
        for value in ({},{'title':''},{'title':'  '},{'title':None},{'title':8},{'title':['Name']},
                      {'title':'x'*151},{'title':'Name','id':'other'},
                      {'title':'Name','project_id':'other'},{'title':'Name','approved_model_version':'0a'},[]):
            with self.subTest(value=value):
                with self.assertRaises(HTTPError) as error:self.request(value=value)
                self.assertEqual(error.exception.code,400)
                self.assertEqual((server.ROOT/'project.json').read_bytes(),self.bytes)
                self.assertEqual(self.backups(),[])

    def test_board_rename_remains_independent(self):
        result=self.request('/api/boards/'+self.board['board_id'],{'title':'Renamed board'})['board']
        self.assertEqual(result['title'],'Renamed board')
        self.assertEqual((server.ROOT/'project.json').read_bytes(),self.bytes)
        self.request(value={'title':'Renamed project'})
        self.assertEqual(server.get_board()['title'],'Renamed board')

    def test_repeated_title_is_noop_and_maximum_length_is_supported(self):
        self.request(value={'title':'Original project'})
        self.assertEqual(self.backups(),[])
        title='x'*150
        self.assertEqual(self.request(value={'title':title})['project']['title'],title)
        self.request(value={'title':title})
        self.assertEqual(len(self.backups()),1)

    def test_missing_config_does_not_create_project(self):
        (server.ROOT/'project.json').rename(server.ROOT/'missing-config.json')
        with self.assertRaises(HTTPError) as error:self.request(value={'title':'Name'})
        self.assertEqual(error.exception.code,400)
        self.assertFalse((server.ROOT/'project.json').exists())
        self.assertEqual(self.backups(),[])


if __name__=='__main__':unittest.main()
