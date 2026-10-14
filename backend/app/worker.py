"""独立预缓存入口；API 也会启动调度，文件锁防止重复同步。"""
import asyncio
from .forecast_cache import sync_loop

if __name__ == '__main__':
    asyncio.run(sync_loop())
