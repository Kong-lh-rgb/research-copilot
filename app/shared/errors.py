class AppError(Exception):
    status_code = 500

class LLMServiceError(AppError):
    status_code = 502