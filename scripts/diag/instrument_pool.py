import os
import sys
import time
import logging
import traceback
import threading
from sqlalchemy import event

logger = logging.getLogger("diag.pool")

# Step 1a: Pool events logger and nested checkout detector
_active_checkouts = {} # thread_ident -> {"conn_id": int, "start_time": float, "thread_name": str}
_lock = threading.Lock()
nested_checkout_events = []
pool_history = []

def instrument_engine_pool(engine):
    @event.listens_for(engine, "checkout")
    def receive_checkout(dbapi_connection, connection_record, connection_proxy):
        tid = threading.get_ident()
        tname = threading.current_thread().name
        now = time.perf_counter()
        conn_id = id(dbapi_connection)
        with _lock:
            if tid in _active_checkouts:
                # NESTED CHECKOUT DETECTED!
                stack = traceback.format_stack(limit=6)
                stack_str = "".join(stack)
                msg = f"NESTED_CHECKOUT: Thread '{tname}' (tid={tid}) already holds conn {active['conn_id']}, attempting second checkout of conn {conn_id}!\nStack (last 6 frames):\n{stack_str}"
                logger.error(msg)
                nested_checkout_events.append({
                    "thread_name": tname,
                    "tid": tid,
                    "existing_conn": _active_checkouts[tid]["conn_id"],
                    "attempted_conn": conn_id,
                    "stack": stack_str,
                    "timestamp": now
                })
            else:
                _active_checkouts[tid] = {
                    "conn_id": conn_id,
                    "checkout_time": now,
                    "thread_name": tname
                }
                logger.debug(f"CHECKOUT: conn={conn_id} thread={tname}")

    @event.listens_for(engine, "checkin")
    def receive_checkin(dbapi_connection, connection_record):
        tid = threading.get_ident()
        tname = threading.current_thread().name
        now = time.perf_counter()
        conn_id = id(dbapi_connection)
        with _lock:
            if tid in _active_checkouts:
                duration_ms = (now - _active_checkouts[tid]["checkout_time"]) * 1000
                logger.debug(f"CHECKIN: conn={conn_id} thread={tname} held={duration_ms:.2f}ms")
                pool_history.append((conn_id, tname, duration_ms))
                del _active_checkouts[tid]
            else:
                logger.debug(f"CHECKIN: conn={conn_id} thread={tname} (untracked)")

    @event.listens_for(engine, "before_cursor_execute")
    def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start_time", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        now = time.perf_counter()
        if "query_start_time" in conn.info and conn.info["query_start_time"]:
            start = conn.info["query_start_time"].pop(-1)
            duration_ms = (now - start) * 1000
            # Statement duration tracked
