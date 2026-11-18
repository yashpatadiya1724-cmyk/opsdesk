import os
import sys
import inspect
import anyio.to_thread

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.app.database import engine, DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT, connect_args
import backend.app.main as main_mod

def run_inspection():
    print("=== A1. ENGINE & SERVER CONFIG RAW ===")
    print(f"DATABASE_URL engine.url: {engine.url}")
    print(f"engine.pool.__class__: {engine.pool.__class__.__name__}")
    print(f"DB_POOL_SIZE: {DB_POOL_SIZE}")
    print(f"DB_MAX_OVERFLOW: {DB_MAX_OVERFLOW}")
    print(f"DB_POOL_TIMEOUT: {DB_POOL_TIMEOUT}")
    print(f"connect_args: {connect_args}")
    print(f"pool status: {engine.pool.status()}")

    # anyio threadpool limit
    import asyncio
    async def get_limiter():
        limiter = anyio.to_thread.current_default_thread_limiter()
        return limiter.total_tokens
    try:
        total_tokens = asyncio.run(get_limiter())
        print(f"anyio.to_thread.current_default_thread_limiter().total_tokens: {total_tokens}")
    except Exception as e:
        print(f"anyio thread limiter error: {e}")

    # Inspect endpoint def vs async def
    print("\n--- Endpoints sync (def) vs async (async def) in backend.app.main ---")
    app = main_mod.app
    for route in app.routes:
        if hasattr(route, "endpoint") and hasattr(route, "path"):
            is_coro = inspect.iscoroutinefunction(route.endpoint)
            kind = "async def" if is_coro else "sync def"
            methods = getattr(route, "methods", set())
            print(f"{list(methods)} {route.path} -> {kind} ({route.endpoint.__name__})")

if __name__ == "__main__":
    run_inspection()
