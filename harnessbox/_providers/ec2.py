"""EC2 sandbox provider — not yet implemented."""

from __future__ import annotations


class EC2Provider:
    """SandboxProvider backed by AWS EC2 instances.

    Requires the ``boto3`` package to be installed separately.
    """

    def __init__(self, **kwargs: object) -> None:
        raise NotImplementedError(
            "EC2Provider is not yet implemented. "
            "Contributions welcome at https://github.com/Nikhil-Kadapala/HarnessBox"
        )
