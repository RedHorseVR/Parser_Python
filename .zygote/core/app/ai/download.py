"""One file download on Qt's network manager: no thread, no timer, no process. The bytes go to the file as they arrive; `progress` says how many
came, `finished` says how it ended. Used by the AI panel to fetch Ollama's installer (one file, from the address the person agreed to)."""
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

STALL_MS = 120000                                           # a transfer that gets no bytes for this long is ended


class Download(QObject):
    progress = Signal('qlonglong', 'qlonglong')                              # bytes received, bytes expected (0 = unknown)
    finished = Signal(bool, str)                             # ok, and the file (ok) or the reason (not ok)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.file = None
        self.target = None

    def start(self, url, target):
        self.target = Path(target)
        self.file = open(self.target, 'wb')
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)    # the file sits behind a redirect
        request.setTransferTimeout(STALL_MS)
        self.reply = self.manager.get(request)
        self.reply.readyRead.connect(self.save)
        self.reply.downloadProgress.connect(self.progress)
        self.reply.finished.connect(self.end)

    def save(self):
        self.file.write(bytes(self.reply.readAll()))

    def end(self):
        self.save()
        self.file.close()
        reply, self.reply = self.reply, None
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        failed = reply.error() != QNetworkReply.NoError or (status is not None and status >= 400)
        message = reply.errorString() if reply.error() != QNetworkReply.NoError else f'HTTP {status}'
        reply.deleteLater()
        if failed:
            self.target.unlink(missing_ok=True)              # a half file is never left behind
            self.finished.emit(False, message)
        else:
            self.finished.emit(True, str(self.target))
