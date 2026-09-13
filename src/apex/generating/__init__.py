"""The build inputs the builder receives, rendered from the release the image targets.

The Containerfiles and the scripts that configure the image, the installer and the live
medium carried the release by hand: the version the base must report, the dist tag of a
pinned package, the vendor directory under the EFI partition. Each is a field of a profile
here, and every rendering is held byte for byte to the file the builder ships, so the
generator is proven on what ships before anything reads from it.
"""
