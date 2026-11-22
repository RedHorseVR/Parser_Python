"""This computer's memory and processor load, read by library calls (ctypes on Windows, /proc on Linux): no program is started.
The panel's live meters call these once a second while the panel is open (DOCTRINE exception, 2026-11-10)."""
import ctypes
import os

from functional.core import ZygoteError


class MemoryStatus(ctypes.Structure):
    _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong), ('ullTotalPhys', ctypes.c_ulonglong),
                ('ullAvailPhys', ctypes.c_ulonglong), ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong), ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]


class ProcessEntry(ctypes.Structure):
    _fields_ = [('dwSize', ctypes.c_ulong), ('cntUsage', ctypes.c_ulong), ('th32ProcessID', ctypes.c_ulong), ('th32DefaultHeapID', ctypes.c_size_t),
                ('th32ModuleID', ctypes.c_ulong), ('cntThreads', ctypes.c_ulong), ('th32ParentProcessID', ctypes.c_ulong),
                ('pcPriClassBase', ctypes.c_long), ('dwFlags', ctypes.c_ulong), ('szExeFile', ctypes.c_char * 260)]


class FileTime(ctypes.Structure):
    _fields_ = [('low', ctypes.c_ulong), ('high', ctypes.c_ulong)]


def windows_time(value):
    return (value.high << 32) | value.low


def memory_mib():
    """(total, used) MiB of this computer's memory. Raises ZygoteError (with the reason) when it cannot be read."""
    if os.name == 'nt':
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ZygoteError('Windows did not give the memory status.')
        return status.ullTotalPhys // 2 ** 20, (status.ullTotalPhys - status.ullAvailPhys) // 2 ** 20
    try:
        values = {}
        with open('/proc/meminfo', encoding='utf-8') as handle:
            for line in handle:
                name, _, rest = line.partition(':')
                values[name] = int(rest.split()[0])
        return values['MemTotal'] // 1024, (values['MemTotal'] - values['MemAvailable']) // 1024
    except (OSError, KeyError, ValueError, IndexError) as error:
        raise ZygoteError(f'The memory of this computer cannot be read here ({error}).') from error


class CpuMeter:
    """How busy the processor is, in percent, between one call and the next (the first call only primes it and answers None)."""

    def __init__(self):
        self.before = None

    def counters(self):
        """(busy, total) time counters since the system started."""
        if os.name == 'nt':
            idle, kernel, user = FileTime(), FileTime(), FileTime()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                raise ZygoteError('Windows did not give the processor times.')
            total = windows_time(kernel) + windows_time(user)                 # kernel time includes the idle time
            return total - windows_time(idle), total
        try:
            with open('/proc/stat', encoding='utf-8') as handle:
                numbers = [int(word) for word in handle.readline().split()[1:]]
        except (OSError, ValueError) as error:
            raise ZygoteError(f'The processor load cannot be read here ({error}).') from error
        idle = numbers[3] + (numbers[4] if len(numbers) > 4 else 0)
        return sum(numbers) - idle, sum(numbers)

    def percent(self):
        now = self.counters()
        before, self.before = self.before, now
        if before is None or now[1] <= before[1]:
            return None
        return max(0, min(100, round(100 * (now[0] - before[0]) / (now[1] - before[1]))))


def child_count(pid):
    """How many programs were started by process `pid` and still run (a shell with none of them sits idle at its prompt). A library call
    (Windows toolhelp snapshot, or /proc); raises ZygoteError when it cannot be told."""
    if os.name == 'nt':
        kernel = ctypes.windll.kernel32
        kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)                   # TH32CS_SNAPPROCESS
        if snapshot in (None, ctypes.c_void_p(-1).value):
            raise ZygoteError('Windows did not list the running programs.')
        try:
            entry = ProcessEntry()
            entry.dwSize = ctypes.sizeof(ProcessEntry)
            count = 0
            more = kernel.Process32First(ctypes.c_void_p(snapshot), ctypes.byref(entry))
            while more:
                count += entry.th32ParentProcessID == pid
                more = kernel.Process32Next(ctypes.c_void_p(snapshot), ctypes.byref(entry))
            return count
        finally:
            kernel.CloseHandle(ctypes.c_void_p(snapshot))
    count = 0
    try:
        for name in os.listdir('/proc'):
            if name.isdigit():
                try:
                    with open(f'/proc/{name}/stat', encoding='utf-8') as handle:
                        fields = handle.read().rpartition(')')[2].split()        # after the "(name)": state, parent pid, …
                except OSError:
                    continue                                                      # that program ended while the list was read
                count += int(fields[1]) == pid
    except (OSError, ValueError, IndexError) as error:
        raise ZygoteError(f'The running programs cannot be listed here ({error}).') from error
    return count
