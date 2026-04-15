import logging

from src.config import CONFIG_PATH, LOG_FILE, load_config
from src.logging_utils import configure_logging
from src.runtime import AppRuntime
from src.tray import TrayController
from src.windows import show_error_message


def main() -> None:
    try:
        config = load_config()
        configure_logging(config.log_level)
        logging.getLogger(__name__).info("Starting switcherino-pc")
        runtime = AppRuntime(config)
        runtime.start()

        if config.tray_enabled:
            tray = TrayController(config, runtime)
            tray.run()
        else:
            if runtime.server_thread is not None:
                runtime.server_thread.join()
    except Exception as exc:
        message = (
            f"Switcherino PC failed to start.\n\n"
            f"Config: {CONFIG_PATH}\n"
            f"Log: {LOG_FILE}\n\n"
            f"Error: {exc}"
        )
        logging.getLogger(__name__).exception("Fatal startup error")
        show_error_message("Switcherino PC", message)
        raise


if __name__ == "__main__":
    main()
