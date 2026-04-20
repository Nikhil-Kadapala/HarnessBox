"""Docker sandbox provider — not yet implemented."""

from __future__ import annotations


class DockerProvider:
    """SandboxProvider backed by local Docker containers.

    Requires the ``docker`` package to be installed separately.
    """

    def __init__(self, **kwargs: object) -> None:
        raise NotImplementedError(
            "DockerProvider is not yet implemented. "
            "Contributions welcome at https://github.com/Nikhil-Kadapala/HarnessBox"
        )
