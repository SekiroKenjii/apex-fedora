"""What the project trusts, and how it checks that a bundle deserves it.

An anchor is a public key with a provenance, and a bundle can never supply its own. A signed
bundle is verified over the same bytes that are then parsed, every file it names is hashed
again, and the negatives prove the verifier refuses what it must.
"""
