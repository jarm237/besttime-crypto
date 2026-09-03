import sys
import os

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes
    import msvcrt

    # flock operation flags
    LOCK_SH = 1
    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
    LOCKFILE_EXCLUSIVE_LOCK = 0x00000002

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_ulonglong),
            ("InternalHigh", ctypes.c_ulonglong),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _kernel32 = ctypes.windll.kernel32
    _LockFileEx = _kernel32.LockFileEx
    _LockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(OVERLAPPED),
    ]
    _LockFileEx.restype = wintypes.BOOL

    _UnlockFileEx = _kernel32.UnlockFileEx
    _UnlockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(OVERLAPPED),
    ]
    _UnlockFileEx.restype = wintypes.BOOL

    def flock(fd, op):
        if isinstance(fd, int):
            file_fd = fd
        elif hasattr(fd, "fileno"):
            file_fd = fd.fileno()
        else:
            file_fd = int(fd)

        try:
            os.lseek(file_fd, 0, os.SEEK_SET)
        except Exception:
            pass

        handle = msvcrt.get_osfhandle(file_fd)

        overlapped = OVERLAPPED()
        overlapped.Offset = 0
        overlapped.OffsetHigh = 0

        if op & LOCK_UN:
            res = _UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped))
            if not res:
                err = ctypes.GetLastError()
                # 158 = ERROR_NOT_LOCKED, safe to ignore on unlock
                if err != 158:
                    raise OSError(err, f"UnlockFileEx failed with error {err}")
            return

        flags = 0
        if op & LOCK_EX:
            flags |= LOCKFILE_EXCLUSIVE_LOCK
        if op & LOCK_NB:
            flags |= LOCKFILE_FAIL_IMMEDIATELY

        res = _LockFileEx(handle, flags, 0, 1, 0, ctypes.byref(overlapped))
        if not res:
            err = ctypes.GetLastError()
            # 33 = ERROR_LOCK_VIOLATION, 108 = ERROR_DRIVE_LOCKED
            if err in (33, 108) or (op & LOCK_NB):
                raise IOError(11, "Resource temporarily unavailable")
            raise OSError(err, f"LockFileEx failed with error {err}")
else:
    # Avoid circular import of ourselves when we are in sys.path
    this_dir = os.path.dirname(__file__)
    saved_path = list(sys.path)
    try:
        while this_dir in sys.path:
            sys.path.remove(this_dir)
        while '' in sys.path:
            sys.path.remove('')
        while '.' in sys.path:
            sys.path.remove('.')
            
        import fcntl as _real_fcntl
        
        LOCK_SH = _real_fcntl.LOCK_SH
        LOCK_EX = _real_fcntl.LOCK_EX
        LOCK_NB = _real_fcntl.LOCK_NB
        LOCK_UN = _real_fcntl.LOCK_UN
        
        def flock(fd, op):
            return _real_fcntl.flock(fd, op)
            
    finally:
        sys.path = saved_path

