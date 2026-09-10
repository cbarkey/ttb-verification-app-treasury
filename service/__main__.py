"""Run the API:  python -m service   (honours HOST / PORT env vars).

This is also where a `.env` file is read. It happens here and nowhere else: the
test suite builds the app through `create_app()` and must never find a real
`ANTHROPIC_API_KEY`, because no test in this project is allowed to touch the
network (N-06). Running the server is an explicit act; importing the app is not.
"""

import os

import uvicorn

from ttbverify.ai.client import load_env_file

if __name__ == "__main__":
    # Names only — never log the values.
    loaded = load_env_file()
    if loaded:
        print(f"loaded from .env: {', '.join(loaded)}")

    uvicorn.run(
        "service.app:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=bool(os.environ.get("RELOAD")),
    )
