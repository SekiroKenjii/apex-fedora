"""Machines: the disks they are layered over, the intent to start one, and the lease that
proves one is running.

Nothing here reaches a hypervisor or a socket directly. Every effect goes through the host
bundle, so the whole context runs on fakes in the fast suite and the same code runs on the
real adapters in the integration tier.
"""
