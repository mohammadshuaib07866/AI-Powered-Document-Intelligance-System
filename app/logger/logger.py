
"""Structured JSON logging for the document-intelligence application."""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime
from pathlib import Path

import structlog
from structlog.stdlib import BoundLogger


LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

LOGGER_NAME = "AIDIS"
LOG_RETENTION = 10

AIDIS_LOG_FILENAME = re.compile(
    r"aidis_(?:\d{4}_\d{6}|\d{8}T\d{6}_\d{6}Z)\.jsonl"
)


class DocumentIntelligenceLogger:
    """Write structured JSON lines to disk and to the console."""

    _configuration_lock = threading.Lock()
    _retention_lock = threading.Lock()
    _structlog_configured = False

    def __init__(
        self,
        log_dir: str | Path = LOG_DIR,
        level: int = logging.INFO,
        console: bool = True,
    ) -> None:
        self.logs_dir = Path(log_dir).expanduser().resolve()
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%d%m_%H%M%S")
        self.log_file_path = self.logs_dir / f"aidis_{timestamp}.jsonl"

        self.level = level
        self.console = console

        self._managed_handlers: list[
            tuple[logging.Logger, logging.Handler]
        ] = []

    @classmethod
    def _configure_structlog(cls) -> None:
        with cls._configuration_lock:
            if cls._structlog_configured:
                return

            structlog.configure(
                processors=[
                    structlog.contextvars.merge_contextvars,
                    structlog.stdlib.add_logger_name,
                    structlog.processors.add_log_level,
                    structlog.processors.TimeStamper(
                        fmt="iso", utc=True, key="timestamp"
                    ),
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.format_exc_info,
                    structlog.processors.EventRenamer(to="event"),
                    structlog.processors.JSONRenderer(),
                ],
                logger_factory=structlog.stdlib.LoggerFactory(),
                wrapper_class=structlog.stdlib.BoundLogger,
                cache_logger_on_first_use=True,
            )

            cls._structlog_configured = True

    def get_logger(self, name: str = LOGGER_NAME) -> BoundLogger:
        """Return a structured logger without adding duplicate handlers."""

        self._configure_structlog()

        logger_name = Path(name).name if name else LOGGER_NAME

        stdlib_logger = logging.getLogger(logger_name)
        stdlib_logger.setLevel(self.level)
        stdlib_logger.propagate = False

        formatter = logging.Formatter("%(message)s")

        file_path = str(self.log_file_path)

        has_file_handler = any(
            getattr(handler, "_aidis_file_path", None) == file_path
            for handler in stdlib_logger.handlers
        )

        if not has_file_handler:
            file_handler = logging.FileHandler(
                self.log_file_path,
                encoding="utf-8",
            )

            file_handler.setLevel(self.level)
            file_handler.setFormatter(formatter)

            file_handler._aidis_file_path = file_path  # type: ignore[attr-defined]

            stdlib_logger.addHandler(file_handler)

            self._managed_handlers.append(
                (stdlib_logger, file_handler)
            )

            self.prune_logs(
                self.logs_dir,
                active_path=self.log_file_path,
            )

        has_console_handler = any(
            getattr(handler, "_aidis_console", False)
            for handler in stdlib_logger.handlers
        )

        if self.console and not has_console_handler:
            console_handler = logging.StreamHandler()

            console_handler.setLevel(self.level)
            console_handler.setFormatter(formatter)

            console_handler._aidis_console = True  # type: ignore[attr-defined]

            stdlib_logger.addHandler(console_handler)

            self._managed_handlers.append(
                (stdlib_logger, console_handler)
            )

        return structlog.get_logger(logger_name)

    @classmethod
    def prune_logs(
        cls,
        log_dir: Path,
        *,
        active_path: Path | None = None,
    ) -> int:
        """Keep the newest AIDIS logs and protect the active log file."""

        removed = 0

        with cls._retention_lock:
            candidates = []

            for path in log_dir.iterdir():

                if (
                    not AIDIS_LOG_FILENAME.fullmatch(path.name)
                    or path.is_symlink()
                ):
                    continue

                try:
                    if path.is_file():
                        candidates.append(
                            (
                                path == active_path,
                                path.stat().st_mtime_ns,
                                path.name,
                                path,
                            )
                        )

                except OSError:
                    continue

            for _, _, _, path in sorted(
                candidates,
                reverse=True,
            )[LOG_RETENTION:]:

                try:
                    path.unlink()
                    removed += 1

                except FileNotFoundError:
                    continue

                except OSError:
                    logging.getLogger(__name__).warning(
                        "Could not remove old AIDIS log: %s",
                        path.name,
                    )

        return removed

    def close(self) -> None:
        """Flush, detach, and close handlers created by this instance."""

        while self._managed_handlers:
            logger, handler = self._managed_handlers.pop()

            logger.removeHandler(handler)
            handler.flush()
            handler.close()

    def __enter__(self) -> "DocumentIntelligenceLogger":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
