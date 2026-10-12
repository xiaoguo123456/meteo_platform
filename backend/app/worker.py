"""天气数据同步任务入口。

后续在这里接入 Open-Meteo S3 与卫星云图下载、校验、转换和本地缓存。
"""

from datetime import datetime, timezone


def run_once() -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    print(f"[{started_at}] 天气数据同步任务入口已启动，当前没有配置数据源。")


if __name__ == "__main__":
    run_once()
