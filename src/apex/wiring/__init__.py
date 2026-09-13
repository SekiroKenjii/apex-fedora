"""The composition root: the one place real adapters are put together and handed out.

Nothing above the CLI and nothing below it builds a bundle of real ports. This package reads
the settings once, resolves the runtime root the settings name, and assembles the host
bundle. A fake anywhere in that bundle would make every recorded result simulated, which is
why this is the most reviewed package in the tree and why its test asserts that every member
it assembles declares the build environment.
"""
