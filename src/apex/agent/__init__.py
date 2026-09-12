"""The program that runs inside a builder, a test guest or the live laptop.

It shares the kernel, the port protocols and the pipeline with the host and nothing else. A
request arrives as a document, a unit runs against the guest's own ports, and the reply goes
back framed, so the host never has to trust an unframed byte the guest wrote.
"""
