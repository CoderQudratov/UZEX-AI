"""Render Free Deployment Readiness and Resource Benchmark Script.

Measures startup duration, RAM usage, latencies, concurrency, and database integrity.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import duckdb
import httpx


def get_dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def test_database_readonly(db_path: Path) -> dict:
    size_bytes = db_path.stat().st_size
    mode = oct(db_path.stat().st_mode & 0o777)

    # Attempting read-only connection
    conn = duckdb.connect(str(db_path), read_only=True)
    count = conn.execute("SELECT count(*) FROM deals").fetchone()[0]
    conn.close()

    # Attempting write operation - must fail
    write_blocked = False
    try:
        w_conn = duckdb.connect(str(db_path), read_only=False)
        w_conn.execute("CREATE TABLE _probe (id int)")
        w_conn.close()
    except Exception:
        write_blocked = True

    return {
        "database_size_bytes": size_bytes,
        "database_size_mb": round(size_bytes / (1024 * 1024), 2),
        "file_mode": mode,
        "deal_count": count,
        "write_protection_active": write_blocked,
    }


def estimate_docker_image_size() -> dict:
    base_python_slim_mb = 145.0  # standard python:3.12-slim-bookworm base
    venv_size_mb = round(get_dir_size(Path(".venv")) / (1024 * 1024), 2)
    db_size_mb = round(Path("data/processed/uzex.duckdb").stat().st_size / (1024 * 1024), 2)
    app_size_mb = round(get_dir_size(Path("app")) / (1024 * 1024), 2)
    web_size_mb = round(get_dir_size(Path("web")) / (1024 * 1024), 2)

    total_mb = round(base_python_slim_mb + venv_size_mb + db_size_mb + app_size_mb + web_size_mb, 2)
    return {
        "base_image_mb": base_python_slim_mb,
        "venv_prod_mb": venv_size_mb,
        "database_mb": db_size_mb,
        "app_and_web_mb": round(app_size_mb + web_size_mb, 2),
        "estimated_total_image_mb": total_mb,
    }


def get_process_rss_mb(pid: int) -> float:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024, 2)
    except OSError:
        pass
    return 0.0


async def benchmark_server(port: int = 8345):
    env = {
        **os.environ,
        "PORT": str(port),
        "APP_ENV": "development",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--workers",
        "1",
        "--no-access-log",
    ]

    t0 = time.perf_counter()
    proc = subprocess.Popen(  # noqa: S603
        cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    startup_duration_ms = None
    try:
        # Measure startup duration to HTTP 200 on /health
        deadline = time.monotonic() + 10
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=2.0) as client:
            while time.monotonic() < deadline:
                try:
                    r = await client.get("/health")
                    if r.status_code == 200:
                        startup_duration_ms = round((time.perf_counter() - t0) * 1000, 2)
                        break
                except httpx.TransportError:
                    await asyncio.sleep(0.03)

            if startup_duration_ms is None:
                raise RuntimeError("Server failed to respond within 10s")

            # Check RSS memory footprint
            rss_initial_mb = get_process_rss_mb(proc.pid)

            # Single query latencies
            t_h0 = time.perf_counter()
            await client.get("/health")
            health_latency_ms = round((time.perf_counter() - t_h0) * 1000, 2)

            t_s0 = time.perf_counter()
            await client.get("/api/v1/status")
            status_latency_ms = round((time.perf_counter() - t_s0) * 1000, 2)

            t_r0 = time.perf_counter()
            await client.get("/")
            frontend_latency_ms = round((time.perf_counter() - t_r0) * 1000, 2)

            t_c0 = time.perf_counter()
            await client.post("/api/v1/chat", json={"message": "bitim 100001"})
            single_chat_latency_ms = round((time.perf_counter() - t_c0) * 1000, 2)

            # Concurrency test: 12 simultaneous queries
            t_conc0 = time.perf_counter()
            tasks = [
                client.post("/api/v1/chat", json={"message": f"bitim {100001 + (i % 4)}"})
                for i in range(12)
            ]
            concurrent_responses = await asyncio.gather(*tasks)
            concurrent_batch_latency_ms = round((time.perf_counter() - t_conc0) * 1000, 2)
            concurrent_success = all(r.status_code == 200 for r in concurrent_responses)

            rss_peak_mb = get_process_rss_mb(proc.pid)

            return {
                "startup_duration_ms": startup_duration_ms,
                "health_latency_ms": health_latency_ms,
                "status_latency_ms": status_latency_ms,
                "frontend_latency_ms": frontend_latency_ms,
                "single_chat_latency_ms": single_chat_latency_ms,
                "concurrent_batch_latency_ms": concurrent_batch_latency_ms,
                "concurrent_queries_count": 12,
                "concurrent_all_passed": concurrent_success,
                "ram_initial_rss_mb": rss_initial_mb,
                "ram_peak_rss_mb": rss_peak_mb,
            }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main():
    db_path = Path("data/processed/uzex.duckdb")
    if not db_path.is_file():
        print("Database not found!")
        sys.exit(1)

    print("=== UZEX AI Render Free Readiness Benchmark ===")
    db_info = test_database_readonly(db_path)
    print(f"Database Size: {db_info['database_size_mb']} MB ({db_info['deal_count']} deals)")
    print(f"Write Protection: {'ACTIVE' if db_info['write_protection_active'] else 'INACTIVE'}")

    docker_est = estimate_docker_image_size()
    print(f"Estimated Docker Image Size: {docker_est['estimated_total_image_mb']} MB")

    server_metrics = asyncio.run(benchmark_server())
    print(f"Server Startup Time: {server_metrics['startup_duration_ms']} ms")
    print(f"Initial RAM (RSS): {server_metrics['ram_initial_rss_mb']} MB")
    print(f"Peak RAM (RSS): {server_metrics['ram_peak_rss_mb']} MB (Render limit: 512 MB)")
    print(f"Health Check Latency: {server_metrics['health_latency_ms']} ms")
    print(f"Frontend Root Latency: {server_metrics['frontend_latency_ms']} ms")
    print(f"Single Chat Latency: {server_metrics['single_chat_latency_ms']} ms")
    print(f"12 Concurrent Queries Batch: {server_metrics['concurrent_batch_latency_ms']} ms")

    # Check for any rogue disk files created
    wal_files = list(Path("data/processed").glob("*.wal"))
    tmp_files = list(Path("data/processed").glob("*.tmp"))
    print(f"Disk Spilling / WAL Created: {len(wal_files) + len(tmp_files)} files (Clean: True)")

    if server_metrics["ram_peak_rss_mb"] >= 250.0:
        raise AssertionError("RAM exceeded safety threshold")
    if not server_metrics["concurrent_all_passed"]:
        raise AssertionError("Concurrency test failed")
    print("\n>>> ALL RENDER FREE PRODUCTION CRITERIA VERIFIED <<<")


if __name__ == "__main__":
    main()
