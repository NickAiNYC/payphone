import asyncio


class MetricsCollector:
    def __init__(self, trace_writer):
        self.trace = trace_writer
        self._stats_task = None

    async def start(self, pc):
        self._stats_task = asyncio.create_task(self._poll_stats(pc))

    async def stop(self):
        if self._stats_task:
            self._stats_task.cancel()

    async def _poll_stats(self, pc):
        while True:
            await asyncio.sleep(10)
            stats = await pc.getStats()
            for report in stats.values():
                if report.type == "inbound-rtp" and report.kind == "audio":
                    pass
