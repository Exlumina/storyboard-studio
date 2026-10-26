import unittest
from unittest.mock import patch
import test_board_store as store_tests
server=store_tests.server

class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.store=store_tests.BoardStoreTests();self.store.setUp()
        self.board=server.get_board();self.code=self.board['nodes'][0]['short_id']
    def tearDown(self):self.store.tearDown()
    def test_native_identifier_copy_and_readback(self):
        with patch.object(server.sys,'platform','darwin'),patch.object(server.shutil,'which',side_effect=lambda name:'/usr/bin/'+name),patch.object(server.subprocess,'run') as write,patch.object(server.subprocess,'check_output',return_value=self.code.encode()):
            result=self.store.request('/api/clipboard','POST',{'text':self.code})
            self.assertEqual(result,{'native_supported':True,'copied':True})
            self.assertEqual(write.call_args.kwargs['input'],self.code.encode())
    def test_wrong_readback_never_claims_copied(self):
        with patch.object(server.sys,'platform','darwin'),patch.object(server.shutil,'which',side_effect=lambda name:'/usr/bin/'+name),patch.object(server.subprocess,'run'),patch.object(server.subprocess,'check_output',return_value=b'changed concurrently'):
            result=server.copy_local_identifier({'text':self.code})
            self.assertFalse(result['copied']);self.assertTrue(result['native_supported'])
            self.assertNotIn('changed concurrently',str(result))
    def test_foreign_or_arbitrary_text_rejected(self):
        with patch.object(server.subprocess,'run') as write:
            for text in ['not a project identifier','',None,'x'*161]:
                with self.assertRaises(ValueError):server.copy_local_identifier({'text':text})
            write.assert_not_called()
    def test_other_hosts_use_browser_clipboard(self):
        with patch.object(server.sys,'platform','linux'),patch.object(server.subprocess,'run') as write:
            self.assertEqual(server.copy_local_identifier({'text':self.code}),{'native_supported':False,'copied':False});write.assert_not_called()

if __name__=='__main__':unittest.main()
