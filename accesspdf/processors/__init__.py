"""Structural remediation processors."""


def _register_all() -> None:
    """Import all processor modules to trigger @register_processor.

    Called lazily by the pipeline to avoid circular imports.
    Import order determines execution order.
    """
    from accesspdf.processors import tagger  # noqa: F401
    from accesspdf.processors import metadata  # noqa: F401
    from accesspdf.processors import reading_order  # noqa: F401
    from accesspdf.processors import headings  # noqa: F401
    from accesspdf.processors import tables  # noqa: F401
    from accesspdf.processors import links  # noqa: F401
    from accesspdf.processors import bookmarks  # noqa: F401
