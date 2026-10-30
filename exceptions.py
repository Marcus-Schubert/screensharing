class ScreenSharingError(Exception):
    """Base exception for the ScreenSharing project."""
    pass

class CastError(ScreenSharingError):
    """Exception raised for errors during Chromecast interaction."""
    pass

class CaptureError(ScreenSharingError):
    """Exception raised for errors during screen capture setup or streaming."""
    pass

class PortalError(ScreenSharingError):
    """Exception raised for errors during xdg-desktop-portal interactions."""
    pass
