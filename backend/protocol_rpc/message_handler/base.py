import os
import json
from functools import wraps
from logging.config import dictConfig
import traceback

from flask import request
from loguru import logger
import sys
import asyncio

from backend.protocol_rpc.message_handler.types import LogEvent
from flask_socketio import SocketIO

from backend.protocol_rpc.configuration import GlobalConfiguration
from backend.protocol_rpc.message_handler.types import EventScope, EventType, LogEvent

MAX_LOG_MESSAGE_LENGTH = 3000


# TODO: this should probably live in another module
def get_client_session_id() -> str:
    try:
        return request.headers.get("x-session-id")
    except RuntimeError:  # when this is called outside of a request
        return ""


class MessageHandler:
    def __init__(self, socketio: SocketIO, config: GlobalConfiguration):
        self.socketio = socketio
        self.config = config
        self.client_session_id = None
        setup_logging_config()

    def with_client_session(self, client_session_id: str):
        new_msg_handler = MessageHandler(self.socketio, self.config)
        new_msg_handler.client_session_id = client_session_id
        return new_msg_handler

    def log_endpoint_info(self, func):
        return log_endpoint_info_wrapper(self, self.config)(func)

    def _socket_emit(self, log_event: LogEvent):
        self.socketio.emit(
            log_event.name,
            log_event.to_dict(),
            to=log_event.client_session_id
            or self.client_session_id
            or get_client_session_id(),
        )

    def _log_message(self, log_event: LogEvent):
        logging_status = log_event.type.value

        if not hasattr(logger, logging_status):
            logging_status = "info"

        log_method = getattr(logger, logging_status)

        message = (
            (log_event.message[:MAX_LOG_MESSAGE_LENGTH] + "...")
            if log_event.message is not None
            and len(log_event.message) > MAX_LOG_MESSAGE_LENGTH
            else log_event.message
        )

        log_message = f"[{log_event.scope.value}] {message}"
        gray = "\033[38;5;245m"
        reset = "\033[0m"

        if log_event.data:
            try:
                data_str = json.dumps(log_event.data, default=lambda o: o.__dict__)
                log_message += f" {gray}{data_str}{reset}"
            except TypeError as e:
                log_message += (
                    f" {gray}{str(log_event.data)} (serialization error: {e}){reset}"
                )

        log_method(log_message)

    def send_message(self, log_event: LogEvent, log_to_terminal: bool = True):
        if log_to_terminal:
            self._log_message(log_event)
        self._socket_emit(log_event)


def log_endpoint_info_wrapper(msg_handler: MessageHandler, config: GlobalConfiguration):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            shouldPrintInfoLogs = (
                func.__name__ not in config.get_disabled_info_logs_endpoints()
            )

            if shouldPrintInfoLogs:
                msg_handler.send_message(
                    LogEvent(
                        "endpoint_call",
                        EventType.INFO,
                        EventScope.RPC,
                        "Endpoint called: " + func.__name__,
                        {"endpoint_name": func.__name__, "args": args},
                    )
                )
            try:
                result = func(*args, **kwargs)
                if hasattr(result, "__await__"):
                    result = await result
                if shouldPrintInfoLogs:
                    msg_handler.send_message(
                        LogEvent(
                            "endpoint_success",
                            EventType.SUCCESS,
                            EventScope.RPC,
                            "Endpoint responded: " + func.__name__,
                            {
                                "endpoint_name": func.__name__,
                                "result": result,
                            },
                        )
                    )
                return result
            except Exception as e:
                msg_handler.send_message(
                    LogEvent(
                        "endpoint_error",
                        EventType.ERROR,
                        EventScope.RPC,
                        f"Error executing endpoint {func.__name__ }: {str(e)}",
                        {
                            "endpoint_name": func.__name__,
                            "error": str(e),
                            "traceback": traceback.format_exc(),
                        },
                    )
                )
                raise e

        return wrapper

    return decorator


def setup_logging_config():
    logging_env = os.environ["LOGCONFIG"]
    file_path = (
        f"backend/protocol_rpc/message_handler/config/logging.{logging_env}.json"
    )
    with open(file_path, "r") as file:
        logging_config = json.load(file)
        dictConfig(logging_config)

    logger.remove()
    logger.add(
        sys.stdout,
        colorize=True,
        format="<level>{level: <8}</level> | {message}",
    )
