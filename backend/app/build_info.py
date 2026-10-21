"""当前运行代码的版本：部署包写入 build_info.json，本地开发直接读取 git。"""
import json
import subprocess
from functools import lru_cache
from pathlib import Path

INFO_PATH = Path(__file__).with_name('build_info.json')


def _git(*args):
    try:
        return subprocess.run(['git', *args], cwd=Path(__file__).parent, capture_output=True,
                              text=True, timeout=3, check=True).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


@lru_cache(maxsize=1)
def build_info():
    # 生产镜像不含 .git，只能依赖部署流程写入的文件；进程内缓存，避免每次请求读盘。
    try:
        info = json.loads(INFO_PATH.read_text())
        return {**info, 'source': 'build'}
    except (FileNotFoundError, ValueError):
        pass
    commit = _git('rev-parse', 'HEAD')
    return {
        'commit': commit,
        'short': commit[:7] if commit else None,
        'committed_at': _git('log', '-1', '--format=%cI'),
        'subject': _git('log', '-1', '--format=%s'),
        'dirty': bool(_git('status', '--porcelain')) if commit else None,
        'source': 'git' if commit else 'unknown',
    }
