from __future__ import annotations


class EstimatorError(Exception):
    pass


class ParseError(EstimatorError):
    pass


class NotManiaError(EstimatorError):
    pass


class UnsupportedKeyError(EstimatorError):
    pass


class ModelUnavailableError(EstimatorError):
    pass
