"""Erorile modulului: mesaje pentru utilizator (422; raportul depus — 409)."""


class ReportError(Exception):
    pass


class ReportFrozen(ReportError):
    pass
