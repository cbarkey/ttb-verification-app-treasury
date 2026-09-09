"""Run the API:  python -m service   (honours HOST / PORT env vars)."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "service.app:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=bool(os.environ.get("RELOAD")),
    )
