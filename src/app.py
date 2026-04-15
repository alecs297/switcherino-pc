import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .autostart import sync_autostart
from .certs import ensure_self_signed_cert, load_cert_info
from .config import AppConfig, load_config
from .controller import ControllerMonitor
from .gaming_mode import GamingModeManager, RemoteSessionSwitchError
from .models import ActionRequest


logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


def check_bearer_auth(
    config: AppConfig,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> None:
    expected = config.api_key.strip()
    provided = credentials.credentials if credentials is not None else ""
    if not expected or provided != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def create_app(config: AppConfig) -> FastAPI:
    manager = GamingModeManager(config)
    steam_task = None
    rpi_status_task = None

    def trigger_enter(trigger: str):
        asyncio.run_coroutine_threadsafe(manager.enter(trigger), loop)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal steam_task, rpi_status_task, loop
        loop = asyncio.get_running_loop()
        local_stop_event = asyncio.Event()
        ensure_self_signed_cert(config.cert_file, config.key_file)
        sync_autostart(config)
        controller.start()
        steam_task = asyncio.create_task(manager.monitor_steam(local_stop_event))
        rpi_status_task = asyncio.create_task(manager.monitor_rpi_status(local_stop_event))
        app.state.manager = manager
        app.state.controller = controller
        yield
        local_stop_event.set()
        controller.stop()
        if steam_task is not None:
            await steam_task
        if rpi_status_task is not None:
            await rpi_status_task

    loop = None
    controller = ControllerMonitor(config, trigger_enter)

    app = FastAPI(
        title="switcherino-pc",
        version="0.1.0",
        lifespan=lifespan,
        description="Windows gaming mode bridge compatible with the Switcherino API shape.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    def auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> None:
        return check_bearer_auth(config, credentials)

    @app.get(
        "/certs",
        tags=["Public"],
        summary="Get certificate pinning material",
        description="Returns certificate information clients can use for TOFU-style pinning.",
    )
    async def certs():
        return JSONResponse({"ok": True, "certs": load_cert_info(config.cert_file, config.suggested_base_url)})

    @app.get(
        "/pc/status",
        tags=["PC"],
        summary="Get PC bridge status",
        description=(
            "Returns local bridge state for the Windows client."
        ),
        responses={
            401: {
                "description": "Bearer token missing or invalid",
                "content": {"application/json": {"example": {"detail": "Unauthorized"}}},
            }
        },
    )
    async def pc_status(_: None = Depends(auth)):
        return JSONResponse(
            {
                "ok": True,
                "status": {
                    **manager.status(),
                    "controller_backend": config.controller_backend,
                    "controller_monitor_running": controller.running,
                },
            }
        )

    async def perform_action(body: ActionRequest, trigger: str):
        try:
            if body.action == "switch_to_game_mode":
                return await manager.enter(trigger)
            if body.action == "switch_to_default_mode":
                return await manager.exit(trigger, request_big_picture_close=True)
        except RemoteSessionSwitchError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        raise HTTPException(
            status_code=400,
            detail=f"Action `{body.action}` is not supported on the PC bridge",
        )

    @app.post(
        "/pc/action",
        tags=["PC"],
        summary="Perform a PC bridge action",
        description=(
            "Control the Windows gaming bridge.\n\n"
            "Supported locally:\n"
            "- `switch_to_game_mode`\n"
            "- `switch_to_default_mode`\n\n"
            "Accepted by the request schema but rejected with `400` on this bridge:\n"
            "- `turn_on`\n"
            "- `turn_off`\n"
            "- `change_source`"
        ),
        openapi_extra={
            "requestBody": {
                "content": {
                    "application/json": {
                        "examples": {
                            "switch_to_game_mode": {
                                "summary": "Enter gaming mode",
                                "value": {"action": "switch_to_game_mode"},
                            },
                            "switch_to_default_mode": {
                                "summary": "Return to default mode",
                                "value": {"action": "switch_to_default_mode"},
                            },
                            "unsupported_change_source": {
                                "summary": "Accepted by schema but unsupported locally",
                                "value": {"action": "change_source", "target": "HDMI_1"},
                            },
                        }
                    }
                }
            }
        },
        responses={
            400: {
                "description": "Unsupported action for the PC bridge or invalid request payload",
                "content": {
                    "application/json": {
                        "examples": {
                            "unsupported_action": {
                                "summary": "Schema-compatible but unsupported locally",
                                "value": {"detail": "Action `change_source` is not supported on the PC bridge"},
                            }
                        }
                    }
                },
            },
            401: {
                "description": "Bearer token missing or invalid",
                "content": {"application/json": {"example": {"detail": "Unauthorized"}}},
            },
            409: {
                "description": "Switch rejected because Windows is running in a Remote Desktop session",
                "content": {
                    "application/json": {
                        "example": {
                            "detail": "Refusing `switch_to_game_mode` because the current Windows session is running over Remote Desktop. Display and audio switching must be triggered from a local session."
                        }
                    }
                },
            },
        },
    )
    async def pc_action(body: ActionRequest, _: None = Depends(auth)):
        return JSONResponse(await perform_action(body, "api"))

    return app


def run() -> None:
    config = load_config()
    ensure_self_signed_cert(config.cert_file, config.key_file)
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        ssl_certfile=config.cert_file,
        ssl_keyfile=config.key_file,
    )
