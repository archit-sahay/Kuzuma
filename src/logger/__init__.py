import gzip
import logging
import os
import shutil
import time
from logging import Logger
from logging.handlers import RotatingFileHandler


def suppress_loggers():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)


class GzipRotatingFileHandler(RotatingFileHandler):
    def doRollover(self):
        print(f"Rotating log file: {self.baseFilename}")

        # Custom rotated log filename using a timestamp
        timestamp = time.strftime("%Y%m%d-%H%M%S")  # Unique timestamp
        rotated_log = f"{self.baseFilename}.{timestamp}"

        # Close the current log file and rotate it
        if self.stream:
            self.stream.close()
            self.stream = None

        # Rotate the log (rename the current log file to the new rotated name)
        os.rename(self.baseFilename, rotated_log)

        # Compress the rotated log file
        gz_filename = rotated_log + ".gz"
        with open(rotated_log, 'rb') as f_in:
            with gzip.open(gz_filename, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        print(f"Compressed {rotated_log} to {gz_filename}")

        # Remove the original uncompressed file
        os.remove(rotated_log)

        # Reopen the current log file (app.log) for new logs
        if not self.delay:
            self.stream = self._open()


def init_logger():
    """
    Initializes the logger with the specified configurations.
    Reads log file path, level, and format from environment variables.
    Configures log rotation and GZIP compression for old logs.
    """
    log_file_path = _get_log_file_path()
    log_level = _get_log_level()
    log_format = _get_log_format()

    # Use print for logger initialization to avoid circular dependency
    print(f"Initializing logger with configurations: \n"
          f"Log file path: {log_file_path} \n"
          f"Log level: {log_level} \n"
          f"Log format: {log_format}")

    # Create the GZIP Rotating File Handler
    handler = GzipRotatingFileHandler(
        filename=log_file_path,
        maxBytes=5 * 1024 * 1024,  # Rotate when log file size exceeds 256MB
        backupCount=0  # Do not delete any logs, we compress and keep them all
    )
    handler.setFormatter(logging.Formatter(log_format))

    # Configure the root logger
    logging.basicConfig(level=log_level, handlers=[handler])

    suppress_loggers()
    print("Logger initialized.")


def get_logger(name: str) -> Logger:
    if name is None or name == "":
        name = "Kazuma: Archit's clone"

    logger: Logger = logging.getLogger(name)
    # Don't override the level if it's already set by the root logger
    if logger.level == logging.NOTSET:
        logger.setLevel(_get_log_level())
    return logger


def _get_log_file_path() -> str:
    default_log_path = "logs/kazuma.log"
    log_file_path = os.environ.get("LOG_FILE_PATH", default_log_path)

    if log_file_path is None or log_file_path == "":
        log_file_path = default_log_path

    if log_file_path is not None and not os.path.exists(log_file_path):
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    return log_file_path


def _get_log_level() -> int:
    log_level = os.environ.get("LOG_LEVEL", "DEBUG")

    if log_level is not None and log_level != "":
        return getattr(logging, log_level.upper(), logging.DEBUG)
    
    return logging.DEBUG


def _get_log_format() -> str:
    default_log_format = "%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s"
    log_format = os.environ.get("LOG_FORMAT", default_log_format)

    if log_format is not None and log_format != "":
        return log_format

    return default_log_format
