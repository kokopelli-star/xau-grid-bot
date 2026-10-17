"""Read-only Windows process discovery. Never starts/stops a terminal or reads credentials."""
from dataclasses import dataclass, field
import sys


class AttachmentUnavailable(RuntimeError):
    REASONS={
        "not_windows":"Windows VPS 上の既存端末だけが対象です。",
        "lookup_failed":"起動済み端末の一覧を読み取れません。",
        "unavailable":"既存端末が見つからないか読み取り不可です。本人が起動・ログイン済みか確認してください。",
        "ambiguous":"起動済み端末が複数あります。本人が確認した --terminal-pid で限定してください。",
        "same_installation":"同じ実行ファイルの複数端末は API が PID で識別できません。診断を中止して本人が構成を確認してください。",
        "exited":"検出した既存端末が終了したため接続しません。",
        "changed":"端末 process が変化したため診断を中止しました。",
    }
    def __init__(self,code):
        self.code=code if code in self.REASONS else "lookup_failed"
        super().__init__(self.REASONS[self.code])


@dataclass
class RunningTerminal:
    pid: int
    path: str = field(repr=False)
    _handle: object = field(repr=False)
    _kernel: object = field(repr=False)

    def alive(self):
        return self._kernel.WaitForSingleObject(self._handle, 0) == 258  # WAIT_TIMEOUT

    def close(self):
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


def find_running_terminal(pid=None, expected_path=None):
    if sys.platform != "win32":
        raise AttachmentUnavailable("not_windows")
    import ctypes
    return _find_with_kernel(ctypes.WinDLL("kernel32",use_last_error=True),pid,expected_path)


def _find_with_kernel(k,pid=None,expected_path=None):
    """Fail closed unless the complete process enumeration is readable."""
    import ctypes
    from ctypes import wintypes as w

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize",w.DWORD),("cntUsage",w.DWORD),("th32ProcessID",w.DWORD),
                    ("th32DefaultHeapID",ctypes.c_size_t),("th32ModuleID",w.DWORD),
                    ("cntThreads",w.DWORD),("th32ParentProcessID",w.DWORD),
                    ("pcPriClassBase",w.LONG),("dwFlags",w.DWORD),("szExeFile",w.WCHAR*260)]

    k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
    k.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)];k.Process32FirstW.restype=w.BOOL
    k.Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)];k.Process32NextW.restype=w.BOOL
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    k.QueryFullProcessImageNameW.restype=w.BOOL
    k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];k.WaitForSingleObject.restype=w.DWORD
    k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
    k.GetLastError.argtypes=[];k.GetLastError.restype=w.DWORD
    snap=k.CreateToolhelp32Snapshot(2,0)
    if snap in (None,ctypes.c_void_p(-1).value):
        raise AttachmentUnavailable("lookup_failed")
    found=[]
    try:
        entry=Entry();entry.dwSize=ctypes.sizeof(entry)
        ok=k.Process32FirstW(snap,ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() in ("terminal64.exe","metatrader64.exe"):
                handle=k.OpenProcess(0x1000|0x100000,False,entry.th32ProcessID)
                if not handle:
                    raise AttachmentUnavailable("lookup_failed")
                target=None
                try:
                    buf=ctypes.create_unicode_buffer(32768);length=w.DWORD(len(buf))
                    if not k.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(length)):
                        raise AttachmentUnavailable("lookup_failed")
                    target=RunningTerminal(int(entry.th32ProcessID),buf.value,handle,k)
                    if not target.alive():
                        raise AttachmentUnavailable("exited")
                    found.append(target)
                except Exception:
                    k.CloseHandle(handle)
                    raise
            ok=k.Process32NextW(snap,ctypes.byref(entry))
        # Process32First/Next use ERROR_NO_MORE_FILES for normal exhaustion.
        # Any other error means uniqueness was never established.
        if k.GetLastError()!=18:
            raise AttachmentUnavailable("lookup_failed")
    except Exception:
        for target in found:target.close()
        raise
    finally:k.CloseHandle(snap)
    return choose_terminal(found,pid,expected_path)


def choose_terminal(found,pid=None,expected_path=None):
    matches=found if pid is None else [target for target in found if target.pid==pid]
    if expected_path is not None:
        import ntpath
        matches=[target for target in matches if ntpath.normcase(ntpath.normpath(target.path))==ntpath.normcase(ntpath.normpath(expected_path))]
    duplicate_path=len(matches)==1 and sum(target.path.casefold()==matches[0].path.casefold() for target in found)>1
    if len(matches)!=1 or duplicate_path:
        for target in found:target.close()
        if not matches:
            raise AttachmentUnavailable("unavailable")
        raise AttachmentUnavailable("same_installation" if duplicate_path else "ambiguous")
    selected=matches[0]
    for target in found:
        if target is not selected:target.close()
    return selected
