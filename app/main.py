from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
import logging
from logging.handlers import RotatingFileHandler
import os

from app.database import connect_to_mongo, close_mongo_connection
from app.routes import auth, notes, functions, vouchers, messages


def setup_logging():
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            RotatingFileHandler(
                'logs/app.log',
                maxBytes=10485760,
                backupCount=5
            ),
            logging.StreamHandler()
        ]
    )

    # Suppress noisy watchfiles logging
    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info("Logging configured successfully")
    return logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")
    await connect_to_mongo()
    yield
    logger.info("Shutting down application...")
    await close_mongo_connection()


logger = setup_logging()

app = FastAPI(
    title="SpotMe",
    description="A multi-tenant application for notes and sandboxed Python functions",
    version="1.0.0",
    lifespan=lifespan
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(notes.router, prefix="/api/notes", tags=["Notes"])
app.include_router(functions.router, prefix="/api/functions", tags=["Functions"])
app.include_router(vouchers.router, prefix="/api/vouchers", tags=["Vouchers"])
app.include_router(messages.router, prefix="/api/messages", tags=["Messages"])


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    logger.info("Login page accessed")
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    logger.info("Register page accessed")
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    logger.info("Dashboard page accessed")
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/notes", response_class=HTMLResponse)
async def notes_page(request: Request):
    logger.info("Notes page accessed")
    return templates.TemplateResponse("notes.html", {"request": request})


@app.get("/functions", response_class=HTMLResponse)
async def functions_page(request: Request):
    logger.info("Functions page accessed")
    return templates.TemplateResponse("functions.html", {"request": request})


@app.get("/function-test", response_class=HTMLResponse)
async def function_test_page(request: Request):
    logger.info("Function test page accessed")
    return templates.TemplateResponse("function-test.html", {"request": request})


@app.get("/vouchers", response_class=HTMLResponse)
async def vouchers_page(request: Request):
    logger.info("Vouchers page accessed")
    return templates.TemplateResponse("vouchers.html", {"request": request})


@app.get("/messages", response_class=HTMLResponse)
async def messages_page(request: Request):
    logger.info("Messages page accessed")
    return templates.TemplateResponse("messages.html", {"request": request})


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
