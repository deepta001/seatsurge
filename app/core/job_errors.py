"""Typed errors for background jobs (CLAUDE.md rule 9): retrying can help, or it can't.

The worker decides what to do from the error's class, never from its message
text. These are separate from DomainError because they never become HTTP
responses; they steer retries inside the worker.
"""


class PermanentError(Exception):
    """Retrying will fail the same way every time (bad data, an unknown event type).

    The job gives up at once instead of wasting attempts.
    """


class TransientError(Exception):
    """Might work if tried again later (a database or Redis blip).

    The message is left unacknowledged and retried with growing delays; after
    too many deliveries it is dead-lettered like a PermanentError. Any other
    unexpected exception is treated the same way.
    """


class InvariantViolation(PermanentError):
    """A database backstop refused a write that should never have been attempted.

    Example: issuing tickets would take a tier past its capacity. It means
    Redis or the app got something wrong; the database stopped an oversell.
    It must stay at zero in every test and in the load test.
    """
