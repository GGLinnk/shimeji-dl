class ShimejiDLError(Exception):
    """Base error raised by shimeji-dl."""


class FetchError(ShimejiDLError):
    """An HTTP resource could not be fetched."""


class ExtractorError(ShimejiDLError):
    """An input could not be extracted."""


class DownloadError(ShimejiDLError):
    """A character could not be downloaded."""
