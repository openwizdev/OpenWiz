"""Errors an agent can handle without reading a traceback."""


class CrmError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

    def payload(self):
        return {"ok": False, "error": {"code": self.code, "message": self.message}}
