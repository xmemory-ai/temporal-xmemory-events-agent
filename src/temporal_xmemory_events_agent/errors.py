"""Exceptions raised by this package."""


class ConfigurationError(Exception):
    """The configuration file, environment or CLI overrides do not describe a runnable setup."""


class MemoryReadError(Exception):
    """A structured memory read came back in a shape the agent cannot act on."""
