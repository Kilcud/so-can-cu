"""V2 intake, security bounds, embedding, evidence and HTTP smoke tests."""
import base64
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document
from pypdf import PdfWriter
import http.client
from app import LocalServer
from store import Store,AppError
from intake_v2 import decode_upload,extract,chunk,create_imported,fetch_public
from ai_v2 import SearchEngine

class V2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name),seed_demo=False)
    def tearDown(self): self.tmp.cleanup()
    def make_docx(self):
        doc=Document();doc.add_heading('Nguồn học liệu có thể kiểm tra',0)
        doc.add_paragraph('Một học liệu phải có cơ quan cung cấp, vị trí đoạn và phiên bản để người đọc đối chiếu nội dung trước khi trích dẫn.')
        out=io.BytesIO();doc.save(out);return out.getvalue()
    def test_docx_import_is_draft_and_carries_locators(self):
        res=create_imported(self.store,'Học liệu thử','Đơn vị thử','',self.make_docx(),'.docx','test.docx')
        self.assertEqual(len(res['created_sources']),1)
        doc=self.store.get_source(res['created_sources'][0]['id'])
        self.assertEqual(doc['source']['status'],'draft')
        self.assertIn('Đoạn Word',doc['segments'][0]['locator'])
        self.assertGreater(len(doc['segments'][0]['text']),20)
        self.assertEqual(self.store.search('học liệu', reviewed_only=True)['count'],0)
    def test_txt_utf8_import(self):
        v=create_imported(self.store,'Tài liệu thử','Tác giả','',('Phần phương pháp khoa học chứa nhiều thông tin cần được kiểm tra lại một cách khách quan.').encode(),' .txt'.strip(),'test.txt')
        self.assertEqual(v['total_segments'],1)
    def test_pdf_no_text_layer(self):
        writer=PdfWriter();writer.add_blank_page(width=300,height=400)
        mem=io.BytesIO();writer.write(mem)
        with self.assertRaises(AppError) as ctx:
            create_imported(self.store,'Bản quét','Tác giả','',mem.getvalue(),'.pdf','test.pdf')
        self.assertEqual(ctx.exception.code,'NO_TEXT_LAYER')
    def test_bad_extension(self):
        with self.assertRaises(AppError): decode_upload({'filename':'x.exe','content_base64':base64.b64encode(b'MZ').decode()})
    def test_overlarge(self):
        with self.assertRaises(AppError): decode_upload({'filename':'x.txt','content_base64':'a'*(12*1024*1024)})
    def test_public_allowlist_blocks_private_and_unknown(self):
        for url in ('http://vbpl.vn/a','https://localhost/a','https://127.0.0.1/a','https://example.com/a','https://vbpl.vn.evil.org/a'):
            with self.assertRaises(AppError,msg=url): fetch_public(url)
    def test_semantic_mocked_no_false_fallback(self):
        doc=create_imported(self.store,'Kiểm tra căn cứ','Giảng viên','',self.make_docx(),'.docx','test.docx')
        sid=doc['created_sources'][0]['id'];self.store.review_source(sid,{'review_note':'Đã đối chiếu tệp thử nghiệm tự tạo và các đoạn Word.'})
        e=SearchEngine(self.store)
        with patch('ai_v2.embed_many',side_effect=lambda xs:[[1.0,0.0] for x in xs]):
            found=e.semantic('Có thể kiểm tra nguồn bằng cách nào')
        self.assertGreater(found['count'],0)
        self.assertEqual(found['mode'],'semantic_ollama')
    def test_rag_citation_rejection_and_success(self):
        doc=create_imported(self.store,'Kiểm tra căn cứ','Giảng viên','',self.make_docx(),'.docx','test.docx')
        self.store.review_source(doc['created_sources'][0]['id'],{'review_note':'Đã kiểm tra trên tệp Word tạo ra cho bài test.'})
        e=SearchEngine(self.store)
        with patch('ai_v2.ollama',return_value={'response':'Cần đối chiếu nguồn trước khi trích dẫn [1].'}):
            ans=e.answer('Tôi cần làm gì trước khi trích dẫn?','keyword')
            self.assertEqual(ans['status'],'generated_unverified')
            self.assertEqual(len(ans['citations']),1)
        with patch('ai_v2.ollama',return_value={'response':'Cứ tin tuyệt đối.'}):
            ans=e.answer('Tôi cần làm gì trước khi trích dẫn?','keyword')
            self.assertEqual(ans['status'],'citation_validation_failed')
    def test_rag_no_source_does_not_call_llm(self):
        e=SearchEngine(self.store)
        with patch('ai_v2.ollama') as mock:
            d=e.answer('Một câu hỏi không có căn cứ?','keyword')
            self.assertEqual(d['status'],'insufficient_evidence')
            mock.assert_not_called()

class HTTPV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.server=LocalServer(0,Path(self.tmp.name),seed_demo=False,quiet=True)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.port=self.server.server_address[1]
        self.token=self.server.csrf_token
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3);self.tmp.cleanup()
    def request(self,method,path,data=None):
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=20)
        body=json.dumps(data,ensure_ascii=False).encode() if data is not None else None
        headers={'Host':f'127.0.0.1:{self.port}','Content-Type':'application/json','X-CSRF-Token':self.token}
        c.request(method,path,body=body,headers=headers)
        r=c.getresponse();val=json.loads(r.read());status=r.status;c.close();return status,val
    def test_upload_then_search_draft_and_review(self):
        d=Document();d.add_paragraph('Quy trình kiểm tra căn cứ yêu cầu ghi rõ phiên bản tài liệu để không dẫn sai đoạn.')
        b=io.BytesIO();d.save(b)
        status,res=self.request('POST','/api/import/file',{'filename':'demo.docx','title':'Tài liệu nghiên cứu','issuer':'Đơn vị thử nghiệm','content_base64':base64.b64encode(b.getvalue()).decode()})
        self.assertEqual(status,201)
        self.assertEqual(res['created_sources'][0]['status'],'draft')
        status,d=self.request('POST','/api/rag/ask',{'question':'Một câu hỏi chưa có tài liệu được duyệt?','mode':'keyword'})
        self.assertEqual(status,200);self.assertEqual(d['status'],'insufficient_evidence')
    def test_semantic_offline_is_explicit_error(self):
        status,d=self.request('POST','/api/search/semantic',{'q':'thử nghiệm'})
        self.assertEqual(status,200);self.assertEqual(d['count'],0)
    def test_reject_public_host(self):
        s,d=self.request('POST','/api/import/public',{'url':'https://example.com/private'})
        self.assertEqual(s,403);self.assertEqual(d['error']['code'],'HOST_NOT_ALLOWED')
    def test_new_static_assets(self):
        c=http.client.HTTPConnection('127.0.0.1',self.port)
        c.request('GET','/ui_v2.js',headers={'Host':f'127.0.0.1:{self.port}'})
        res=c.getresponse();self.assertEqual(res.status,200);self.assertIn(b'renderImport',res.read());c.close()

if __name__=='__main__': unittest.main()
