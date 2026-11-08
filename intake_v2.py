"""User-triggered ingestion of DOCX, PDF, TXT and allowlisted public HTTPS pages.
No crawler or background download. Imported items remain unreviewed.
"""
import base64
import binascii
import html.parser
import io
import ipaddress
import re
import socket
import zipfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from store import AppError

MAX_FILE = 8 * 1024 * 1024
ALLOWED_HOSTS = {"vbpl.vn", "vanban.chinhphu.vn", "chinhphu.vn", "moet.gov.vn", "mps.gov.vn"}


def decode_upload(payload):
    filename = str(payload.get('filename', '')).strip()
    if not filename or len(filename) > 180 or filename != Path(filename).name or '/' in filename or '\\' in filename:
        raise AppError('INVALID_FILENAME', 'Tên tệp không hợp lệ.')
    suffix = Path(filename).suffix.lower()
    if suffix not in {'.pdf', '.docx', '.txt'}:
        raise AppError('UNSUPPORTED_FILE', 'Chỉ nhận PDF có lớp chữ, DOCX hoặc TXT. Không nhận DOC có macro.', 415)
    encoded = payload.get('content_base64')
    if not isinstance(encoded, str) or len(encoded) > ((MAX_FILE * 4 // 3) + 128):
        raise AppError('FILE_TOO_LARGE', 'Giới hạn 8 MiB cho mỗi tệp.', 413)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise AppError('INVALID_BASE64', 'Dữ liệu tải lên bị lỗi.', 400)
    if not raw or len(raw) > MAX_FILE:
        raise AppError('FILE_TOO_LARGE', 'Tệp rỗng hoặc vượt 8 MiB.', 413)
    if suffix == '.pdf' and not raw.startswith(b'%PDF'):
        raise AppError('FILE_MISMATCH', 'Tệp không có định dạng PDF hợp lệ.', 415)
    if suffix == '.docx' and not raw.startswith(b'PK'):
        raise AppError('FILE_MISMATCH', 'Tệp không có định dạng DOCX hợp lệ.', 415)
    if suffix == '.docx':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if sum(x.file_size for x in z.infolist()) > 40 * 1024 * 1024:
                    raise AppError('DOCX_TOO_LARGE', 'DOCX giải nén vượt 40 MiB.', 413)
        except AppError: raise
        except zipfile.BadZipFile: raise AppError('DOCX_PARSE_FAILED', 'Cấu trúc nén DOCX không hợp lệ.',422)
    return filename, suffix, raw


class VisibleHTML(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []
        self.title = ''
        self.in_title = False
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','nav','footer','header','noscript','svg','form'):
            self.skip += 1
        if tag == 'title': self.in_title = True
        if tag in ('p','article','section','h1','h2','h3','li','div','tr','br') and not self.skip:
            self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script','style','nav','footer','header','noscript','svg','form') and self.skip:
            self.skip -= 1
        if tag == 'title': self.in_title = False
    def handle_data(self, data):
        if self.in_title: self.title += data.strip() + ' '
        if not self.skip and not self.in_title: self.parts.append(data)


def extract(raw, suffix):
    blocks = []
    if suffix == '.txt':
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise AppError('INVALID_ENCODING', 'TXT phải được lưu dưới dạng UTF-8.', 422)
        blocks = [('Văn bản', s) for s in re.split(r'\n\s*\n', text)]
    elif suffix == '.docx':
        try:
            from docx import Document
            d = Document(io.BytesIO(raw))
            # Word does not reliably carry pagination; indicate paragraphs, not guessed pages.
            blocks = [(f'Đoạn Word {i}', p.text) for i,p in enumerate(d.paragraphs, 1) if p.text.strip()]
            for ti,t in enumerate(d.tables, 1):
                for ri,row in enumerate(t.rows, 1):
                    blocks.append((f'Bảng {ti}, hàng {ri}', ' | '.join(c.text for c in row.cells)))
        except Exception:
            raise AppError('DOCX_PARSE_FAILED', 'Không thể đọc DOCX. Kiểm tra tệp và cấu trúc tài liệu.', 422)
    elif suffix == '.pdf':
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw), strict=False)
            if len(reader.pages) > 250:
                raise AppError('TOO_MANY_PAGES', 'Bản mẫu giới hạn 250 trang PDF.', 422)
            for i,p in enumerate(reader.pages, 1):
                page_text = p.extract_text() or ''
                blocks.extend((f'Trang {i}', s) for s in re.split(r'\n\s*\n', page_text))
        except AppError: raise
        except Exception:
            raise AppError('PDF_PARSE_FAILED', 'Không thể tách lớp chữ PDF; PDF quét ảnh cần OCR riêng.', 422)
    elif suffix == '.html':
        doc = VisibleHTML()
        doc.feed(raw.decode('utf-8', 'replace'))
        blocks = [('Trang web', s) for s in re.split(r'\n\s*\n', ''.join(doc.parts))]
    else:
        raise AppError('UNSUPPORTED_FILE', 'Định dạng không được hỗ trợ.', 415)
    return [(loc, re.sub(r'\s+', ' ', txt).strip()) for loc,txt in blocks if len(re.sub(r'\s+', ' ', txt).strip()) >= 20]


def chunk(blocks, target=1250):
    """Short locatable paragraphs merged; long paragraphs split without discarding tails."""
    out=[]
    for loc, text in blocks:
        for part_no, offset in enumerate(range(0,len(text),target), 1):
            t=text[offset:offset+target].strip()
            if len(t) < 20 and out:
                out[-1]['text'] += ' ' + t
                continue
            if len(t) < 20: continue
            out.append({'title': f'{loc}'[:250], 'locator': f'{loc} · phần {part_no}'[:250], 'text': t})
    return out


def create_imported(store, title, issuer, url, raw, suffix, filename):
    blocks=extract(raw,suffix)
    if sum(len(text) for _, text in blocks) > 1_500_000:
        raise AppError('DOCUMENT_TOO_LARGE', 'Nội dung trích xuất vượt 1,5 triệu ký tự.',422)
    segments=chunk(blocks)
    if not segments:
        raise AppError('NO_TEXT_LAYER', 'Không tách được đủ chữ. PDF quét ảnh cần OCR và kiểm tra lại.',422)
    if len(segments)>1200:
        raise AppError('DOCUMENT_TOO_LARGE', 'Tài liệu có quá nhiều đoạn; hãy chia thành các tệp nhỏ.',422)
    # Existing source version cap: <=100 segments and <=180,000 characters.
    parts=[]; current=[]; length=0
    for seg in segments:
        if current and (len(current)>=90 or length+len(seg['text'])>160000):
            parts.append(current);current=[];length=0
        current.append(seg);length+=len(seg['text'])
    if current: parts.append(current)
    created=[]
    for i, part in enumerate(parts,1):
        name=title+(f' (phần {i}/{len(parts)})' if len(parts)>1 else '')
        out=store.create_source({'title':name[:300], 'issuer':issuer[:200], 'document_number':'', 'published_date':'', 'url':url, 'kind':'learning_note','text_kind':'original','segments':part})
        created.append({'id':out['source']['id'],'title':name,'segments':len(part),'status':'draft'})
    return {'created_sources':created,'total_segments':len(segments),'origin':filename,'warning':'Tài liệu mới chưa được đối chiếu; văn bản trích xuất có thể sai bố cục. Phải kiểm tra trước khi dùng làm căn cứ.'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AppError('REDIRECT_DENIED', 'Không tự theo chuyển hướng; hãy kiểm tra địa chỉ đích.',422)


def fetch_public(url):
    if not isinstance(url,str) or len(url)>2000:
        raise AppError('INVALID_URL','URL không hợp lệ.',422)
    try:
        p=urlsplit(url)
        host=p.hostname.lower() if p.hostname else ''
        if p.scheme!='https' or host not in ALLOWED_HOSTS or p.port not in (None,443) or p.username or p.password:
            raise AppError('HOST_NOT_ALLOWED','Chỉ đồng bộ HTTPS từ danh sách miền công khai được phê duyệt.',403)
    except ValueError:
        raise AppError('INVALID_URL','URL không hợp lệ.',422)
    # DNS-check decreases SSRF risk; prototype is not a production hardened crawler.
    try:
        for record in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
            addr=ipaddress.ip_address(record[4][0])
            if not addr.is_global:
                raise AppError('PUBLIC_IP_REQUIRED','Không kết nối tới địa chỉ nội bộ, loopback hoặc địa chỉ không công khai.',403)
    except socket.gaierror:
        raise AppError('DNS_FAILED','Không phân giải được miền nguồn.',422)
    req=urllib.request.Request(url,headers={'User-Agent':'SoCanCu-Research/2.0 (manual import)','Accept':'application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document, text/html, text/plain'})
    opener=urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req,timeout=12) as resp:
            length=resp.headers.get('Content-Length','0')
            if length.isdigit() and int(length)>MAX_FILE: raise AppError('FILE_TOO_LARGE','Nguồn vượt 8 MiB.',413)
            mime=resp.headers.get_content_type()
            b=resp.read(MAX_FILE+1)
            if len(b)>MAX_FILE: raise AppError('FILE_TOO_LARGE','Nguồn vượt 8 MiB.',413)
    except AppError: raise
    except (urllib.error.URLError,TimeoutError):
        raise AppError('FETCH_FAILED','Không tải được trang công khai. Hãy kiểm tra kết nối và quyền truy cập.',422)
    suffix={ 'application/pdf':'.pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document':'.docx','text/html':'.html','text/plain':'.txt'}.get(mime)
    if not suffix:
        raise AppError('UNSUPPORTED_CONTENT_TYPE','Nguồn không trả HTML, PDF, DOCX hoặc TXT.',415)
    return suffix,b
