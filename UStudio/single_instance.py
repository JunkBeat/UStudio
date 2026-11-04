"""Only one UStudio window at a time.

Two copies working on the same game files would fight over them ("file in use by another
process"), so a second launch hands control to the running one — which comes to the front —
and exits. Uses a local socket named per Windows user: the running copy listens, a later copy
connects; if nobody answers, a leftover name from a crashed run is simply taken over."""

import getpass
import os

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

_ACTIVATE = b"activate"


def _server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name available: one shared name is fine
        user = "user"
    return f"UStudio.AssetBrowser.{user}"


class SingleInstance(QObject):
    """acquire() -> True if this is the only copy (keep going), False if another copy is
    already running and was asked to come to the front (exit now)."""

    activation_requested = pyqtSignal()

    def __init__(self, name: str = "", parent=None):
        super().__init__(parent)
        self._name = name or _server_name()
        self._server = None

    def _running_copy_answers(self) -> bool:
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if not sock.waitForConnected(500):
            return False
        sock.write(_ACTIVATE)
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return True

    def acquire(self) -> bool:
        if os.environ.get("USTUDIO_ALLOW_MULTIPLE") == "1":
            return True
        if self._running_copy_answers():
            return False
        QLocalServer.removeServer(self._name)  # a name left behind by a crashed copy
        server = QLocalServer(self)
        if not server.listen(self._name):
            # Lost a race with another copy starting at the same moment.
            return not self._running_copy_answers()
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._on_data(s))
            sock.disconnected.connect(sock.deleteLater)
            if sock.bytesAvailable():
                self._on_data(sock)

    def _on_data(self, sock) -> None:
        if bytes(sock.readAll()) == _ACTIVATE:
            self.activation_requested.emit()
