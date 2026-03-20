# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""
Railway startup script.

Reads PORT from the environment (Railway injects it at runtime) and starts
uvicorn. Using Python instead of a shell command avoids all ${PORT:-8000}
quoting/expansion issues across Dockerfile CMD and railway.toml startCommand.
"""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True,
    )
