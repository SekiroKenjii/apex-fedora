"""The host's half of each fixture: what is asked of a guest, and what its answer must look
like.

A fixture is built or mutated inside a builder or a disposable guest. The steps that run there
belong to the agent. What lives here is everything that can be decided without a guest: the
shapes, the parsers, the derivations that were pure in the older scripts, and the refusals
that keep a fixture from being mistaken for a release artifact.
"""
