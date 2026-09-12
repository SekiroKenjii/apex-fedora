"""Files that move into the package byte for byte, and are wrapped in types afterwards.

A safety artifact the older tree ships, such as the installer's preflight, is not rewritten
here. It is carried under its own name with a `.verbatim` suffix, so nothing scans it as
code, and a typed module elsewhere loads it and exposes what the product calls.
"""
