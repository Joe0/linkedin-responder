"""Entry point — run with: python main.py  (requires Python 3.12 / miniconda env)"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "app.web:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
