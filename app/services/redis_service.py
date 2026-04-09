import redis.asyncio as redis
import os
import time

class RateLimiterService:
    def __init__(self):
        self.redis_client = redis.from_url(
            f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}",
            encoding="utf-8",
            decode_responses=True 
        )

    async def is_rate_limited(self, team_id: str, limits: list[tuple[int, int]]) -> bool:
        now = time.time()
        keys_and_windows = []

        for limit, window in limits:
            current_window = int(now // window)
            key = f"rate_limit:{team_id}:{window}:{current_window}"
            keys_and_windows.append((key, limit, window))

        current_counts = await self.redis_client.mget([k[0] for k in keys_and_windows])

        for i, count in enumerate(current_counts):
            limit = keys_and_windows[i][1]
            if count and int(count) >= limit:
                return True

        async with self.redis_client.pipeline(transaction=True) as pipe:
            for key, limit, window in keys_and_windows:
                pipe.incr(key)
                pipe.expire(key, window)
            await pipe.execute()
        
        return False
    
rate_limiter = RateLimiterService()