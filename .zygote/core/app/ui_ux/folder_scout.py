"""The folder scout: ONE background thread that reads folder lists, so the window never waits for the disk.

A folder the window asks for (want) is read before the read-ahead plan, newest ask first. Asking for a folder to show (tag 'view') cancels
the older 'view' asks that are still waiting (their model rows go back to "not asked", the signal `dropped` says which). A read that has
started cannot be taken back (the operating system may hold it for a long time); its answer is kept for later and the window is not waiting
for it. The thread only reads names (core.list_folder), touches no window, starts at the first ask and ends with Zygote (stop())."""
import collections
import threading
import time

from PySide6.QtCore import QObject, Signal

from functional import core

FRESH_SECONDS = 3                                              # a read this young is used again as it is


class FolderScout(QObject):
    ready = Signal(str)                                        # a folder has been read (its path); delivered on the window's thread
    dropped = Signal(str)                                      # an older ask was cancelled by a newer one

    def __init__(self):
        super().__init__()
        self.cache = {}                                        # path -> (time read, entries)
        self.lock = threading.Condition()
        self.wants = []                                        # [tag, path, fresh]: the newest is taken first
        self.plans = collections.deque()
        self.reading = None                                    # the path being read now
        self.stopping = False
        self.thread = None

    def start(self):
        if self.thread is None:
            self.stopping = False
            self.thread = threading.Thread(target=self.work, name='folder-scout', daemon=True)
            self.thread.start()

    def entries(self, path):
        """The entries read for a folder, or None when it has not been read (or not lately enough: older than FRESH_SECONDS)."""
        found = self.cache.get(str(path))
        if found is not None and time.monotonic() - found[0] < FRESH_SECONDS:
            return found[1]
        return None

    def want(self, path, tag='tree', fresh=False):
        """Read this folder first. tag 'view' (the folder to show) cancels the older waiting 'view' asks."""
        path = str(path)
        cancelled = []
        with self.lock:
            if tag == 'view':
                cancelled = [item[1] for item in self.wants if item[0] == 'view' and item[1] != path]
                self.wants = [item for item in self.wants if not (item[0] == 'view' and item[1] != path)]
            self.wants = [item for item in self.wants if item[1] != path]
            self.wants.append([tag, path, fresh])
            self.lock.notify()
        self.start()
        for name in cancelled:
            self.dropped.emit(name)

    def plan(self, folders):
        """Read these folders when nothing is asked for, in this order (the read-ahead)."""
        with self.lock:
            for folder in folders:
                if str(folder) not in self.cache and str(folder) not in self.plans:
                    self.plans.append(str(folder))
            self.lock.notify()
        self.start()

    def idle(self):
        with self.lock:
            return not self.wants and not self.plans and self.reading is None

    def stop(self):
        if self.thread is not None:
            with self.lock:
                self.stopping = True
                self.lock.notify()
            self.thread.join(2)
            self.thread = None

    def work(self):
        while True:
            with self.lock:
                while not self.wants and not self.plans and not self.stopping:
                    self.lock.wait()
                if self.stopping:
                    return
                if self.wants:
                    _, path, fresh = self.wants.pop()
                else:
                    path, fresh = self.plans.popleft(), False
                self.reading = path
            if fresh or self.entries(path) is None:
                self.cache[path] = (time.monotonic(), core.list_folder(path))
            with self.lock:
                self.reading = None
            self.ready.emit(path)
