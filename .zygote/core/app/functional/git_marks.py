"""Which files of a project are changed since the last commit, read straight from Git's own index file (.git\\index). No Git program is started and nothing is
written: the index lists every tracked file with its size and time; a file whose size and time are the same is clean, one that differs is read and compared by
its content hash. The answer is {path: 'ok' | 'bad'} for the files and for every folder above them ('bad' wins; the project itself is the empty path).
Files Git does not track show no mark. Only called from the window's own thread of work (marks_scout), never from the views."""
import hashlib
import os
import struct
from pathlib import Path


def read_index(index_file):
    """The tracked entries of a Git index (versions 2, 3 and 4): [(path, mtime_seconds, mtime_nanoseconds, size, sha1 hex, mode)]. [] when there is none."""
    index_file = Path(index_file)
    if not index_file.is_file():
        return []
    data = index_file.read_bytes()
    if data[:4] != b'DIRC':
        raise ValueError(f'{index_file} is not a Git index.')
    version, count = struct.unpack('>II', data[4:12])
    if version not in (2, 3, 4):
        raise ValueError(f'The Git index version {version} is not known.')
    entries, at, previous = [], 12, b''
    for _ in range(count):
        start = at
        seconds, nanoseconds = struct.unpack('>II', data[at:at + 8])
        mode, = struct.unpack('>I', data[at + 24:at + 28])
        size, = struct.unpack('>I', data[at + 36:at + 40])
        sha = data[at + 40:at + 60].hex()
        flags, = struct.unpack('>H', data[at + 60:at + 62])
        at += 62
        if version >= 3 and flags & 0x4000:
            at += 2
        if version == 4:
            strip, shift = 0, 0
            while True:                                           # the number of bytes cut from the end of the previous path (a varint)
                byte = data[at]
                at += 1
                strip |= (byte & 0x7f) << shift
                if not byte & 0x80:
                    break
                shift += 7
                strip += 1 << shift
            end = data.index(b'\0', at)
            name = previous[:len(previous) - strip] + data[at:end]
            at = end + 1
        else:
            end = data.index(b'\0', at)
            name = data[at:end]
            at = end + 1
            at = start + ((at - start + 7) // 8) * 8                # version 2 and 3 pad each entry to a multiple of 8
        previous = name
        if flags & 0x3000:                                        # a conflict stage above 0: the file is in the middle of a merge
            pass
        entries.append((name.decode('utf-8', 'replace'), seconds, nanoseconds, size, sha, mode))
    return entries


def blob_hash(content):
    return hashlib.sha1(b'blob %d\0' % len(content) + content).hexdigest()


def same_content(path, size, sha):
    """True when the file's content is the one the index names (a Windows file with CRLF line ends is compared with LF, as Git does with autocrlf)."""
    content = Path(path).read_bytes()
    return blob_hash(content) == sha or blob_hash(content.replace(b'\r\n', b'\n')) == sha


def file_state(path, seconds, nanoseconds, size, sha):
    """'ok' or 'bad' for one tracked file."""
    try:
        stat = os.lstat(path)
    except OSError:
        return 'bad'                                              # deleted
    if stat.st_size == size and stat.st_mtime_ns // 1_000_000_000 == seconds and (not nanoseconds or stat.st_mtime_ns % 1_000_000_000 == nanoseconds):
        return 'ok'
    try:
        return 'ok' if same_content(path, size, sha) else 'bad'
    except OSError:
        return 'bad'


def states(project):
    """{relative path with forward slashes: 'ok' | 'bad'} for the tracked files and all their folders, and '' for the project itself."""
    root = Path(project)
    result = {}
    for name, seconds, nanoseconds, size, sha, mode in read_index(root / '.git' / 'index'):
        if mode == 0o160000:                                      # a submodule: its folder is shown as clean (what is inside it is its own repository)
            state = 'ok'
        else:
            state = file_state(root / name, seconds, nanoseconds, size, sha)
        parts = name.split('/')
        for at in range(len(parts), -1, -1):
            key = '/'.join(parts[:at])
            if result.get(key) != 'bad':
                result[key] = 'bad' if state == 'bad' else result.get(key, 'ok')
    return result
