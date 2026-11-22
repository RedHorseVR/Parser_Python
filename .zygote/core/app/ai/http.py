"""One small asynchronous HTTP client on Qt's network manager. A call returns at once; `done(ok, data)` is called later in the window's
thread with the decoded JSON (ok True) or the reason (ok False, a text). Nothing is retried and nothing is guessed."""
import functools
import json

from PySide6.QtCore import QByteArray, QObject, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


class Http(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)

    def call(self, method, url, body, done, timeout_ms=15000):
        """Send one request. method: GET, POST or DELETE. body: a dict (sent as JSON) or None."""
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.ContentTypeHeader, 'application/json')
        request.setTransferTimeout(timeout_ms)
        data = QByteArray(json.dumps(body).encode('utf-8')) if body is not None else QByteArray()
        if method == 'GET':
            reply = self.manager.get(request)
        elif method == 'POST':
            reply = self.manager.post(request, data)
        elif method == 'DELETE':
            reply = self.manager.sendCustomRequest(request, QByteArray(b'DELETE'), data)
        else:
            raise ValueError(f'Unknown HTTP method {method!r}')
        reply.finished.connect(functools.partial(self.finished, reply, url, done))

    def stream(self, url, body, on_event, done, stall_ms=120000):
        """POST and read the answer line by line while it comes (see Stream). stall_ms: no bytes for this long ends it."""
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.ContentTypeHeader, 'application/json')
        request.setTransferTimeout(stall_ms)
        Stream(self.manager.post(request, QByteArray(json.dumps(body).encode('utf-8'))), on_event, done, self)

    @staticmethod
    def reason(raw, status):
        """The server's own words when it gave any ({"error": "..."}), else the status."""
        try:
            text = json.loads(raw).get('error')
        except (ValueError, AttributeError):
            text = None
        return text or raw.decode('utf-8', 'replace')[:300] or f'HTTP {status}'

    def finished(self, reply, url, done):
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        raw = bytes(reply.readAll())
        failed = reply.error() != QNetworkReply.NoError
        message = reply.errorString()
        reply.deleteLater()
        if status is None:
            done(False, f'{url}: {message}' if failed else f'{url}: no answer')
        elif status >= 400:
            done(False, f'{url}: {self.reason(raw, status)} (HTTP {status})')
        else:
            try:
                done(True, json.loads(raw))
            except ValueError:
                done(False, f'{url}: the answer is not JSON')


class Stream(QObject):
    """One POST whose answer is a stream of JSON lines (Ollama's pull): `on_event(dict)` for each line as it arrives, then `done(ok, reason)`."""

    def __init__(self, reply, on_event, done, parent=None):
        super().__init__(parent)
        self.reply = reply
        self.on_event = on_event
        self.done = done
        self.buffer = b''
        reply.readyRead.connect(self.read)
        reply.finished.connect(self.end)

    def read(self):
        self.buffer += bytes(self.reply.readAll())
        *lines, self.buffer = self.buffer.split(b'\n')
        for line in lines:
            self.one_line(line)

    def one_line(self, line):
        if not line.strip():
            return
        try:
            self.on_event(json.loads(line))
        except ValueError:
            self.on_event({'error': f'unreadable line from the server: {line[:80]!r}'})

    def end(self):
        self.read()
        self.one_line(self.buffer)
        status = self.reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        failed = self.reply.error() != QNetworkReply.NoError
        message = self.reply.errorString()
        self.reply.deleteLater()
        if status is None or failed or status >= 400:
            self.done(False, message if failed or status is None else f'HTTP {status}')
        else:
            self.done(True, None)
        self.deleteLater()
