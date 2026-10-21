# errors.py
# Any code can raise AppError("friendly message", http_status). main.py (a later
# part) turns it into a clean error for the user instead of a Python traceback.


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class LLMError(AppError):
    """Problems talking to an LLM provider (rate limit, bad key, outage)."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message, status_code)