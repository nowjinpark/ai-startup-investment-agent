"""공개 자료 수집과 실제 PDF 쪽수 관리."""

from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import re
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request, robotparser
from xml.sax.saxutils import escape

from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _setting(settings, name, default):
    return settings.get(name, default) if isinstance(settings, dict) else getattr(settings, name, default)


def _safe_url(url):
    parts = parse.urlsplit(url)
    sensitive = {"key", "api_key", "apikey", "token", "servicekey", "access_token", "auth"}
    query = [(k, "REDACTED" if k.lower() in sensitive else v) for k, v in parse.parse_qsl(parts.query)]
    return parse.urlunsplit((parts.scheme, parts.netloc.split("@")[-1], parts.path, parse.urlencode(query), ""))


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Collector:
    def __init__(self, settings, output_dir):
        self.settings = settings
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "documents").mkdir(exist_ok=True)
        self.max_pages = min(200, max(0, int(_setting(settings, "max_pages", 200))))
        self.per_source = max(1, int(_setting(settings, "max_pages_per_source", 8)))
        self.timeout = max(1, float(_setting(settings, "request_timeout", 20)))
        self.interval = max(0.2, float(_setting(settings, "request_interval", 1)))
        self.byte_limit = max(1024, int(_setting(settings, "max_download_mb", 25) * 1024 * 1024))
        self.user_agent = _setting(settings, "user_agent", "PhysicalAIRAG/1.0")
        self.allowed_domains = _setting(settings, "allowed_domains", [])
        self.sources = []
        self.errors = []
        self._hashes = {}
        self._robots = {}
        self._crawl_delays = {}
        self._last_request = {}
        self._opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())
        manifest = self.output_dir / "sources.json"
        error_log = self.output_dir / "collection_errors.json"
        if error_log.exists():
            self.errors = json.loads(error_log.read_text(encoding="utf-8"))
        if manifest.exists():
            loaded = json.loads(manifest.read_text(encoding="utf-8"))
            self.sources = loaded if isinstance(loaded, list) else loaded["sources"]
            for source in self.sources:
                if not (self.output_dir / source["file"]).is_file():
                    raise ValueError("수집 기록의 PDF 파일이 없습니다. 새 출력 폴더로 실행하세요.")
                self._hashes[source["content_hash"]] = source
            if self.page_count > self.max_pages:
                raise ValueError("기존 수집 자료가 설정한 페이지 한도를 초과합니다.")

    @property
    def page_count(self):
        return len(self._hashes)

    def export_pdf(self):
        if not self.sources or len(self.sources) != self.page_count or self.page_count > self.max_pages:
            raise ValueError("수집 기록과 실제 페이지 한도를 확인해야 합니다.")
        writer = PdfWriter()
        for index, source in enumerate(self.sources):
            reader = PdfReader(self.output_dir / source["file"])
            if len(reader.pages) != 1:
                raise ValueError("수집 기록의 개별 PDF는 각각 1쪽이어야 합니다.")
            writer.add_page(reader.pages[0])
            writer.add_outline_item(f'{index + 1}. {source["title"]} [{source["source_id"]}]', index)
        writer.add_metadata({"/Title": "RAG 수집 원문", "/Subject": f"등록 원문 {self.page_count}쪽"})
        target = self.output_dir / "rag-documents.pdf"
        temporary = target.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            writer.write(stream)
        if len(PdfReader(temporary).pages) != self.page_count:
            temporary.unlink(missing_ok=True)
            raise ValueError("통합 PDF의 실제 쪽수가 수집 기록과 다릅니다.")
        temporary.replace(target)
        return target

    def _save(self):
        for name, value in (("sources.json", self.sources), ("collection_errors.json", self.errors)):
            path = self.output_dir / name
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)

    def _error(self, url, reason, code="collection_failed"):
        self.errors.append({"url": _safe_url(str(url)), "code": code, "reason": reason, "at": _now()})
        self._save()

    def _validate_url(self, url):
        parts = parse.urlsplit(url)
        if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("공개 HTTP(S) 주소만 수집할 수 있습니다.")
        if parts.port not in {None, 80, 443}:
            raise ValueError("일반 웹 포트만 사용할 수 있습니다.")
        host = parts.hostname.rstrip(".").lower()
        if self.allowed_domains and not any(host == d or host.endswith("." + d) for d in self.allowed_domains):
            raise ValueError("허용한 자료 사이트에 포함되지 않습니다.")
        addresses = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("내부망·로컬 주소는 수집하지 않습니다.")

    def _robot_allowed(self, url):
        parts = parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = robotparser.RobotFileParser()
            try:
                data, _, _ = self._download(origin + "/robots.txt", check_robots=False, size_limit=256 * 1024)
                parser.parse(data.decode("utf-8-sig", errors="replace").splitlines())
            except error.HTTPError as exc:
                if exc.code == 404:
                    parser.parse([])
                else:
                    raise ValueError("robots.txt 접근을 확인하지 못했습니다. 공개 PDF를 직접 저장해 추가하세요.") from exc
            self._robots[origin] = parser
            self._crawl_delays[parts.netloc] = parser.crawl_delay(self.user_agent) or 0
        return self._robots[origin].can_fetch(self.user_agent, url)

    def _download(self, url, check_robots=True, size_limit=None):
        limit = size_limit or self.byte_limit
        for _ in range(6):
            self._validate_url(url)
            if check_robots and not self._robot_allowed(url):
                raise ValueError("사이트가 자동 수집을 허용하지 않는 주소입니다.")
            host = parse.urlsplit(url).netloc
            delay = max(self.interval, self._crawl_delays.get(host, 0)) - (time.monotonic() - self._last_request.get(host, 0))
            if delay > 0:
                time.sleep(delay)
            self._last_request[host] = time.monotonic()
            req = request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "text/html,application/pdf,text/plain"})
            try:
                response = self._opener.open(req, timeout=self.timeout)
            except error.HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                    url = parse.urljoin(url, exc.headers["Location"])
                    exc.close()
                    continue
                raise
            with response:
                if int(response.headers.get("Content-Length", "0")) > limit:
                    raise ValueError("파일이 다운로드 크기 한도를 초과합니다.")
                result = bytearray()
                started = time.monotonic()
                while True:
                    block = response.read(min(65536, limit + 1 - len(result)))
                    if not block:
                        break
                    result.extend(block)
                    if len(result) > limit:
                        raise ValueError("파일이 다운로드 크기 한도를 초과합니다.")
                    if time.monotonic() - started > self.timeout:
                        raise ValueError("자료 다운로드 시간을 초과했습니다.")
                return bytes(result), url, response.headers.get("Content-Type", "")
        raise ValueError("주소 이동 횟수를 초과했습니다.")

    @staticmethod
    def _html(data):
        soup = BeautifulSoup(data, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else "웹 자료"
        date = soup.select_one('meta[property="article:published_time"], meta[name="date"], time[datetime]')
        published = (date.get("content") or date.get("datetime")) if date else None
        for node in soup.select("script,style,noscript,nav,header,footer,aside,form,svg,iframe,[hidden],.advertisement,.ads"):
            node.decompose()
        main = soup.select_one("article, main, [role=main], .entry-content, #content") or soup.body or soup
        # 투자사 목록의 기업 소개와 공식 홈페이지 주소를 함께 보존합니다.
        for anchor in main.select('a[href]'):
            label = anchor.get_text(' ', strip=True)
            link = anchor.get('href', '')
            if label and link.startswith(('https://', 'http://')) and len(label) <= 350:
                anchor.replace_with(f'{label} ({_safe_url(link)})')
        # 표의 열 관계를 유지하여 기업명·투자단계를 함께 읽습니다.
        for row in main.find_all("tr"):
            row.replace_with(" | ".join(cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])) + "\n")
        text = "\n".join(line.strip() for line in main.get_text("\n", strip=True).splitlines() if line.strip())
        return text, title, published

    def links(self, url, limit=20):
        try:
            data, resolved, content_type = self._download(url)
            if "pdf" in content_type or data.startswith(b"%PDF"):
                return []
            soup = BeautifulSoup(data, "html.parser")
            found, seen = [], set()
            for anchor in soup.select("a[href]"):
                link = parse.urldefrag(parse.urljoin(resolved, anchor["href"]))[0]
                if parse.urlsplit(link).scheme not in {"http", "https"} or link in seen:
                    continue
                seen.add(link)
                found.append({"url": link, "title": anchor.get_text(" ", strip=True)})
                if len(found) >= max(0, limit):
                    break
            return found if limit > 0 else []
        except Exception as exc:
            self._error(url, self._failure(exc))
            return []

    @staticmethod
    def _failure(exc):
        if isinstance(exc, error.HTTPError):
            return f"HTTP {exc.code}: 직접 접근할 수 없습니다. 공개 자료 파일로 보완하세요."
        if isinstance(exc, (ValueError, FileNotFoundError)):
            return str(exc)[:240]
        return f"{type(exc).__name__}: 자료를 읽지 못했습니다. 주소와 파일을 확인하세요."

    def collect(self, url, company_id, doc_type, title=None, pages=None, required_terms=None):
        try:
            if self._non_evidence_page(url, title):
                return []
            data, resolved, content_type = self._download(url)
            return self._collect_bytes(data, company_id, doc_type, resolved, title, content_type, pages, required_terms)
        except Exception as exc:
            self._error(url, self._failure(exc))
            return []

    def _non_evidence_page(self, url, title=None):
        path = parse.unquote(parse.urlsplit(url).path).rstrip('/').rsplit('/', 1)[-1]
        stem = path.rsplit('.', 1)[0] if '.' in path else path
        normalize = lambda value: re.sub(r'[\s_-]', '', value.casefold())
        excluded = {'privacy', 'privacypolicy', 'terms', 'termsofservice', 'termsandconditions',
                    'login', 'signin', '개인정보처리방침', '개인정보보호정책', '이용약관'}
        title_parts = re.split(r'\s*[|–—>]\s*|\s+-\s+', title or '')
        if normalize(stem) in excluded or any(normalize(part) in excluded for part in title_parts):
            self._error(url, '개인정보처리방침·이용약관·로그인 페이지는 기업 분석 자료에서 제외합니다.', 'non_evidence_page')
            return True
        return False

    def add_local(self, path, company_id, doc_type, url="", title=None, pages=None):
        try:
            path = Path(path)
            if path.stat().st_size > self.byte_limit:
                raise ValueError("파일이 크기 한도를 초과합니다.")
            types = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/plain", ".html": "text/html", ".htm": "text/html"}
            if path.suffix.lower() not in types:
                raise ValueError("PDF·HTML·TXT·MD 자료만 추가할 수 있습니다.")
            return self._collect_bytes(path.read_bytes(), company_id, doc_type, url, title or path.stem, types[path.suffix.lower()], pages)
        except Exception as exc:
            self._error(url or str(path), self._failure(exc))
            return []

    def _text_pdf(self, text, title, url):
        font_path = Path(__file__).parent / "assets" / "NanumGothic-Regular.ttf"
        font = "CorpusKorean"
        if font not in pdfmetrics.getRegisteredFontNames():
            if font_path.exists():
                pdfmetrics.registerFont(TTFont(font, str(font_path)))
            else:
                font = "HYSMyeongJo-Medium"
                pdfmetrics.registerFont(UnicodeCIDFont(font))
        buffer = io.BytesIO()
        body = ParagraphStyle("body", fontName=font, fontSize=10, leading=15, wordWrap="CJK", spaceAfter=5)
        heading = ParagraphStyle("title", parent=body, fontSize=14, leading=20, spaceAfter=10)
        flow = [Paragraph(escape(title), heading)]
        if url:
            flow.extend([Paragraph(escape(_safe_url(url)), body), Spacer(1, 8)])
        # 긴 한 문단도 ReportLab이 실제 A4 페이지로 나눕니다.
        flow.extend(Paragraph(escape(line), body) for line in text.splitlines() if line.strip())
        SimpleDocTemplate(buffer, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42).build(flow)
        return buffer.getvalue()

    def _company_related(self, text, required_terms, url):
        if required_terms is None:
            return True
        if not isinstance(required_terms, list) or not required_terms or any(not isinstance(term, str) or not term.strip() for term in required_terms):
            raise ValueError("required_terms에는 기업명·별칭의 비어 있지 않은 문자열 목록을 넣으세요.")
        normalized = "".join(text.casefold().split())
        if any("".join(term.casefold().split()) in normalized for term in required_terms):
            return True
        self._error(url, "원문 본문에서 대상 기업명·별칭을 확인하지 못해 기업 자료로 저장하지 않았습니다.", "company_unrelated")
        return False

    def _collect_bytes(self, data, company_id, doc_type, url, title, content_type, pages=None, required_terms=None):
        if self._non_evidence_page(url, title):
            return []
        doc_types = [doc_type] if isinstance(doc_type, str) else list(doc_type)
        if not company_id or not doc_types or any(t not in {"company", "technology", "market"} for t in doc_types):
            raise ValueError("기업 ID와 company/technology/market 자료 유형을 지정하세요.")
        published = None
        original_pdf = data.startswith(b"%PDF")
        if not original_pdf:
            if "html" in content_type:
                text, parsed_title, published = self._html(data)
                if self._non_evidence_page(url, parsed_title):
                    return []
                title = title or parsed_title
            elif "text/plain" in content_type:
                text = data.decode("utf-8-sig")
            else:
                raise ValueError("PDF나 읽을 수 있는 웹 본문이 아닙니다.")
            if len(text.strip()) < 80:
                raise ValueError("본문이 너무 짧습니다. 로그인·스크립트 전용 페이지는 공개 PDF로 보완하세요.")
            # 검색 결과 제목·URL에 기업명이 있어도 실제 본문이 관련되어야 합니다.
            if not self._company_related(text, required_terms, url):
                return []
            data = self._text_pdf(text, title or "웹 자료", url)
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("암호로 보호된 PDF는 수집할 수 없습니다.")
        extracted = {}
        if original_pdf and required_terms is not None:
            extracted = {i: (page.extract_text() or "").strip() for i, page in enumerate(reader.pages)}
            if not self._company_related("\n".join(extracted.values()), required_terms, url):
                return []
        if pages is not None:
            if not isinstance(pages, list) or not pages or any(type(p) is not int or p < 1 or p > len(reader.pages) for p in pages):
                raise ValueError("pages에는 실제 PDF의 1부터 시작하는 유효한 쪽수 목록을 넣으세요.")
            indices = sorted({p - 1 for p in pages})
        else:
            indices = range(len(reader.pages))
        output, skipped = [], 0
        for selected_index, index in enumerate(indices):
            if selected_index >= self.per_source:
                skipped += 1
                continue
            page = reader.pages[index]
            text = extracted[index] if index in extracted else (page.extract_text() or "").strip()
            if len(text) < 30:
                self._error(url, f"원본 {index + 1}쪽: 추출 가능한 본문이 부족합니다. 표·이미지 자료는 OCR 또는 원문 확인이 필요합니다.", "no_text")
                continue
            key = _digest(" ".join(text.split()))
            if key in self._hashes:
                source = self._hashes[key]
                source["doc_types"] = sorted(set(source["doc_types"] + doc_types))
                if source["company_id"] != company_id:
                    self._error(url, "동일 원문이 다른 기업에 이미 배정되어 원래 기업 ID를 유지합니다. 기업별 근거의 관련성을 확인하세요.", "company_mismatch")
                if source not in output:
                    output.append(source)
                continue
            if self.page_count >= self.max_pages:
                skipped += 1
                continue
            relative = f"documents/{key[:24]}.pdf"
            writer = PdfWriter()
            writer.add_page(page)
            with (self.output_dir / relative).open("wb") as stream:
                writer.write(stream)
            source = {
                "source_id": "S-" + key[:16], "company_id": company_id,
                "doc_type": doc_types[0], "doc_types": doc_types,
                "title": title or "공개 PDF 자료", "url": _safe_url(url),
                "published_at": published, "collected_at": _now(),
                "original_page": index + 1 if original_pdf else None,
                "saved_page": 1, "rendered_page": index + 1, "text": text, "file": relative,
                "content_hash": key,
            }
            self.sources.append(source)
            self._hashes[key] = source
            output.append(source)
        if skipped:
            self._error(url, f"문서별 {self.per_source}쪽 또는 전체 {self.max_pages}쪽 한도로 {skipped}쪽을 미수집했습니다. 필요한 원본 쪽을 별도 PDF로 추려 보완하세요.", "page_limit")
        self._save()
        return output
