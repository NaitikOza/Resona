from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.api.websocket import router as websocket_router
from app.dependencies import get_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_database().initialize()
    yield


app = FastAPI(
    title="Resona Local API",
    version="0.1.0",
    description=(
        "Local emergency documentation with speech transcription and evidence-linked reports."
    ),
    telemetry={"auto_configure": False},
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)
app.include_router(api_router)
app.include_router(websocket_router)


@app.exception_handler(HTTPException)
async def http_error(_: Request, error: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"success": False, "error": str(error.detail)},
    )


@app.exception_handler(Exception)
async def unhandled_error(_: Request, error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": f"Local service error: {error}"},
    )

