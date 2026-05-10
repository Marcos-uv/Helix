#!/usr/bin/env python
import sys
import os
import logging

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('server.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
logger.info("Starting server...")

if __name__ == "__main__":
    import uvicorn
    logger.info("Importing app...")
    from backend.main import app
    logger.info("App imported successfully")
    logger.info("Starting uvicorn...")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="debug")
