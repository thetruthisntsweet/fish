"""Hold a WebSocket to /ws/echo open and check that it survives (T2.1 §10, §17).

The client sends no keepalive pings of its own, like a browser: only the server's pings
keep the connection alive, so this tests exactly what real players will experience.
Between echoes the connection sits idle for ``--every`` seconds.

    uv run python scripts/ws_soak.py wss://<your-staging-host>/ws/echo --minutes 30
    uv run python scripts/ws_soak.py ws://localhost:8000/ws/echo --minutes 0.25 --every 5

Exits 0 and prints PASS if every echo came back; exits 1 with the reason otherwise.
"""

import argparse
import asyncio
import sys
import time

import websockets


async def soak(url: str, minutes: float, every: float) -> None:
    start = time.monotonic()
    deadline = start + minutes * 60
    async with websockets.connect(url, ping_interval=None) as ws:
        print(f"connected; server said: {await ws.recv()}")
        count = 0
        while (remaining := deadline - time.monotonic()) > 0:
            await asyncio.sleep(min(every, remaining))
            count += 1
            message = f"soak {count}"
            await ws.send(message)
            reply = await asyncio.wait_for(ws.recv(), timeout=10)
            if reply != message:
                raise RuntimeError(f"echo mismatch: sent {message!r}, got {reply!r}")
            print(f"{(time.monotonic() - start) / 60:6.2f} min: echo {count} ok")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hold a WebSocket to /ws/echo open; check it survives."
    )
    parser.add_argument("url", help="ws:// or wss:// URL of /ws/echo")
    parser.add_argument("--minutes", type=float, default=30.0, help="how long to hold (30)")
    parser.add_argument("--every", type=float, default=300.0, help="idle seconds per echo (300)")
    args = parser.parse_args()
    try:
        asyncio.run(soak(args.url, args.minutes, args.every))
    except (OSError, TimeoutError, RuntimeError, websockets.ConnectionClosed) as error:
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
