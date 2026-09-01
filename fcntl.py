import sys
import os

if sys.platform == 'win32':
    # flock operation flags
    LOCK_SH = 1
    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def flock(fd, op):
        pass
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
