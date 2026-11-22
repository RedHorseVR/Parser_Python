"""The process side of a terminal: a program running behind a pseudo-terminal. No Qt here.

Windows uses ConPTY through pywinpty (the package `winpty`); Linux and macOS use the standard library's pty. Both are the same class family
(`PtyIO`): `spawn`, `write`, `resize`, `terminate`, `is_alive`, and two callbacks the owner sets:
    stdout_callback(bytes)    called from the read thread with what the program printed
    terminated_callback(int)  called once, from the read thread, with the exit code (-1 when unknown)
One program per object. `spawn` is only called from a button press (DOCTRINE Part 4: processes).
The program is a child of Zygote; on Windows ConPTY adds one console-host helper next to it (authorized 2026-11-09: one program plus one helper per press)."""
import os
import threading

from functional.core import ZygoteError


class PtyIO:
    def __init__(self, command, cwd, rows, cols):
        if not command:
            raise ZygoteError('Nothing to run: the command is empty.')
        self.command = [str(word) for word in command]
        self.cwd = str(cwd)
        self.rows = max(1, int(rows))
        self.cols = max(1, int(cols))
        self.stdout_callback = lambda data: None
        self.terminated_callback = lambda code: None
        self.running = False
        self.stop_requests = 0
        self.lock = threading.Lock()

    def spawn(self):
        raise NotImplementedError

    def write(self, data):
        raise NotImplementedError

    def resize(self, rows, cols):
        raise NotImplementedError

    def kill(self):
        raise NotImplementedError

    def terminate(self, force=False):
        """The first call asks the program to end; a second call forces it. force=True forces at once (a shell has nothing to save)."""
        self.stop_requests += 1
        self.kill() if (force or self.stop_requests > 1) else self.ask_to_end()

    def ask_to_end(self):
        raise NotImplementedError

    def is_alive(self):
        return self.running

    def has_children(self):
        """True while the shell has a program of its own running (a library call; raises ZygoteError when it cannot be told)."""
        from ai.system import child_count
        return child_count(self.process.pid) > 0

    def finish(self, code):
        """Called once by the read thread when the program is gone."""
        with self.lock:
            if not self.running:
                return
            self.running = False
        self.terminated_callback(code)


class WindowsPty(PtyIO):
    """ConPTY through pywinpty: PtyProcess.spawn(argv, cwd=, dimensions=(rows, cols)); read() blocks and returns text."""

    def spawn(self):
        try:
            import winpty
        except ImportError as error:
            raise ZygoteError('pywinpty is not installed in the Zygote environment. Run app_tree\\bat\\RUN.bat once so that it installs what '
                              '.zygote\\config\\requirements.txt lists.') from error
        try:
            self.process = winpty.PtyProcess.spawn(self.command, cwd=self.cwd, dimensions=(self.rows, self.cols))
        except Exception as error:                                   # pywinpty raises several kinds; every one is shown
            raise ZygoteError(f'The program could not be started in the terminal: {error}. Command: {" ".join(self.command)}') from error
        self.running = True
        threading.Thread(name='Zygote terminal reader', target=self.read_loop, daemon=True).start()

    def read_loop(self):
        try:
            while True:
                text = self.process.read(4096)
                if not text:
                    if not self.process.isalive():
                        break
                    continue
                self.stdout_callback(text.encode('utf-8') if isinstance(text, str) else text)
        except (EOFError, OSError):
            pass                                                     # the pseudo-console closed: the program is gone
        self.finish(self.exit_code())

    def exit_code(self):
        try:
            code = self.process.wait() if hasattr(self.process, 'wait') else self.process.exitstatus
        except Exception:
            return -1
        return -1 if code is None else int(code)

    def write(self, data):
        if self.running:
            self.process.write(data.decode('utf-8', 'replace') if isinstance(data, bytes) else data)

    def resize(self, rows, cols):
        self.rows, self.cols = max(1, int(rows)), max(1, int(cols))
        if self.running:
            self.process.setwinsize(self.rows, self.cols)

    def ask_to_end(self):
        if self.running:
            self.process.terminate(force=False)

    def kill(self):
        if self.running:
            self.process.terminate(force=True)


class PosixPty(PtyIO):
    """The standard library's pty: a master/slave pair, the program started with the slave as its terminal. Used on Linux and macOS."""

    def spawn(self):
        import fcntl
        import pty
        import struct
        import subprocess
        import termios
        master, slave = pty.openpty()
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', self.rows, self.cols, 0, 0))
        env = dict(os.environ, TERM=os.environ.get('TERM', 'xterm-256color'), COLUMNS=str(self.cols), LINES=str(self.rows))
        try:
            self.process = subprocess.Popen(self.command, stdin=slave, stdout=slave, stderr=slave, cwd=self.cwd, env=env,
                                            start_new_session=True, close_fds=True)
        except OSError as error:
            os.close(master)
            os.close(slave)
            raise ZygoteError(f'The program could not be started in the terminal: {error}. Command: {" ".join(self.command)}') from error
        os.close(slave)
        self.master = master
        self.running = True
        threading.Thread(name='Zygote terminal reader', target=self.read_loop, daemon=True).start()

    def read_loop(self):
        import select
        try:
            while True:
                ready, _, _ = select.select([self.master], [], [], 0.2)
                if ready:
                    data = os.read(self.master, 4096)
                    if not data:
                        break
                    self.stdout_callback(data)
                elif self.process.poll() is not None:
                    break
        except OSError:
            pass                                                     # EIO: the program closed its end
        code = self.process.wait()
        os.close(self.master)
        self.finish(code)

    def write(self, data):
        if self.running:
            os.write(self.master, data if isinstance(data, bytes) else data.encode('utf-8'))

    def resize(self, rows, cols):
        import fcntl
        import struct
        import termios
        self.rows, self.cols = max(1, int(rows)), max(1, int(cols))
        if self.running:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack('HHHH', self.rows, self.cols, 0, 0))

    def ask_to_end(self):
        if self.running:
            self.process.terminate()

    def kill(self):
        if self.running:
            self.process.kill()


def make_pty(command, cwd, rows, cols):
    """The right PtyIO for this system (not started)."""
    return (WindowsPty if os.name == 'nt' else PosixPty)(command, cwd, rows, cols)
