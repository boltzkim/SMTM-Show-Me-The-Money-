"""Domain exceptions for SMTM."""


class SMTMError(Exception):
    """Base error for domain failures."""


class ConfigurationError(SMTMError):
    """Raised when a configuration file is invalid."""


class DataProviderError(SMTMError):
    """Raised when market data cannot be loaded or normalized."""


class RiskRejected(SMTMError):
    """Raised when a request is rejected by risk rules."""


class TraderError(SMTMError):
    """Raised by trader and exchange adapters."""

