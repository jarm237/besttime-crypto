import sys
import os
import time
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

import pytest
import fcntl


def test_fcntl_same_process_thread_lock(tmp_path):
    lock_file = tmp_path / "test.lock"
    
    def lock_unlock(worker_id):
        with lock_file.open("a+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            time.sleep(0.01)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return worker_id

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lock_unlock, range(10)))
    assert len(results) == 10


def test_fcntl_nonblocking_raises_error(tmp_path):
    lock_file = tmp_path / "nb.lock"
    f1 = lock_file.open("a+")
    fcntl.flock(f1.fileno(), fcntl.LOCK_EX)
    
    f2 = lock_file.open("a+")
    with pytest.raises((IOError, OSError)):
        fcntl.flock(f2.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        
    fcntl.flock(f1.fileno(), fcntl.LOCK_UN)
    f1.close()
    f2.close()


def test_fcntl_subprocess_concurrency(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    lock_file = tmp_path / "subproc.lock"
    code = f"""
import sys
sys.path.insert(0, r"{repo_root}")
import fcntl, time
with open(r"{lock_file}", "a+") as f:
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    time.sleep(0.1)
    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
"""
    script = tmp_path / "worker.py"
    script.write_text(code, encoding="utf-8")

    env = {**os.environ, "PYTHONPATH": str(repo_root)}
    processes = [
        subprocess.Popen([sys.executable, str(script)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(3)
    ]
    for p in processes:
        stdout, stderr = p.communicate()
        assert p.returncode == 0, f"Process failed with stderr: {stderr.decode()}"

