"""Local-only styling delivery checks; these do not evaluate RAG quality."""
import http.client
import tempfile
import threading
import unittest
from pathlib import Path
from app import LocalServer

class StyleDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.server=LocalServer(0,Path(self.tmp.name),seed_demo=False,quiet=True)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.port=self.server.server_address[1]
    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        self.thread.join(timeout=3); self.tmp.cleanup()
    def get(self,path):
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        c.request('GET',path)
        r=c.getresponse(); result=(r.status,dict(r.getheaders()),r.read())
        c.close(); return result
    def test_local_font_css_uses_no_remote_cdn(self):
        status,headers,data=self.get('/ui-font.css')
        self.assertEqual(status,200)
        self.assertIn('text/css',headers['Content-Type'])
        self.assertIn(b'local("Nunito")',data)
        self.assertNotIn(b'https://',data)
        self.assertNotIn(b'http://',data)
    def test_styles_have_green_palette_and_rounded_font_stack(self):
        status,_,data=self.get('/styles.css')
        self.assertEqual(status,200)
        self.assertIn(b'#006b3c',data)
        self.assertIn(b'Nunito,Comfortaa',data)
    def test_font_route_does_not_open_arbitrary_files(self):
        status,_,_=self.get('/fonts/../../store.py')
        self.assertEqual(status,404)
    def test_font_csp_remains_self_only(self):
        status,headers,_=self.get('/ui-font.css')
        self.assertEqual(status,200)
        self.assertIn("font-src 'self'",headers['Content-Security-Policy'])
    def test_index_requests_font_css_from_same_origin(self):
        status,_,data=self.get('/')
        self.assertEqual(status,200)
        self.assertIn(b'href="/ui-font.css"',data)
        self.assertNotIn(b'fonts.googleapis.com',data)
