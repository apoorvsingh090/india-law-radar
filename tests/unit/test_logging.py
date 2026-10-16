"""Logging tests (Milestone 1)."""
import logging

from lawradar.logging_config import get_logger, reset_for_tests, setup_logging


def test_setup_logging_returns_named_logger():
    reset_for_tests()
    logger = setup_logging("INFO")
    assert logger.name == "lawradar"
    assert isinstance(get_logger("lawradar.foo"), logging.Logger)


def test_setup_logging_is_idempotent_and_respects_level():
    reset_for_tests()
    setup_logging("DEBUG")
    setup_logging("ERROR")
    assert logging.getLogger().level == logging.ERROR
    reset_for_tests()
    setup_logging("INFO")
