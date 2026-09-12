"""podman and skopeo, run through the process port with the older scripts' arguments."""

from __future__ import annotations

from apex.config import defaults
from apex.kernel import claims, commands, errors, identifiers, safepaths, timing
from apex.ports import containers, process

PODMAN = "podman"
SKOPEO = "skopeo"
ID_FORMAT = "{{.Id}}"


class PodmanEngine(containers.ContainerEnginePort):
    environment = claims.EnvironmentKind.BUILD

    def __init__(self, processes: process.ProcessPort) -> None:
        self._processes = processes

    def image_id(self, name: str) -> identifiers.ImageId:
        text = self._output(
            commands.Argv.of(PODMAN, "image", "inspect", "--format", ID_FORMAT, name),
            deadline=defaults.ENGINE_QUERY_DEADLINE,
        ).decode().strip()
        return identifiers.ImageId.parse(text if text.startswith("sha256:") else f"sha256:{text}")

    def inspect(self, name: str) -> bytes:
        return self._output(
            commands.Argv.of(PODMAN, "image", "inspect", name),
            deadline=defaults.ENGINE_QUERY_DEADLINE,
        )

    def manifest(self, reference: containers.ImageReference) -> bytes:
        return self._output(
            commands.Argv.of(SKOPEO, "inspect", "--raw", str(reference)),
            deadline=defaults.ENGINE_QUERY_DEADLINE,
        )

    def build(self, request: containers.BuildRequest) -> None:
        argv = [PODMAN, "build"]
        if request.label_disabled:
            argv += ["--security-opt", "label=disable"]
        if request.network_none:
            argv.append("--network=none")
        if request.pull_never:
            argv.append("--pull=never")
        if not request.layers:
            argv.append("--layers=false")
        for name, value in request.build_arguments.items():
            argv += ["--build-arg", f"{name}={value}"]
        if request.containerfile is not None:
            argv += ["-f", str(request.containerfile)]
        argv += ["-t", request.tag, str(request.context)]
        self._output(commands.Argv.of(*argv), deadline=defaults.ENGINE_BUILD_DEADLINE)

    def run(self, request: containers.RunRequest) -> commands.CompletedRun:
        argv = [PODMAN, "run", "--rm"]
        if request.read_only:
            argv.append("--read-only")
        if request.network_none:
            argv += ["--network", "none"]
        if request.entrypoint is not None:
            argv += ["--entrypoint", request.entrypoint]
        argv.append(request.image)
        argv.extend(request.argv)
        return self._processes.run(
            commands.Argv.of(*argv),
            deadline=defaults.ENGINE_BUILD_DEADLINE,
            limit=commands.OutputLimit.default(),
        )

    def copy(
        self,
        source: containers.ImageReference,
        destination: containers.ImageReference,
        *,
        policy: safepaths.SafePath | None,
        signing: containers.SigstoreSigning | None,
    ) -> None:
        argv = [SKOPEO]
        if policy is not None:
            argv += ["--policy", str(policy)]
        argv += ["copy", "--preserve-digests"]
        if signing is not None:
            argv += [
                "--sign-by-sigstore-private-key", str(signing.private_key),
                "--sign-passphrase-file", str(signing.passphrase),
                "--sign-identity", signing.identity,
            ]
        argv += [str(source), str(destination)]
        self._output(commands.Argv.of(*argv), deadline=defaults.ENGINE_BUILD_DEADLINE)

    def generate_sigstore_key(
        self, *, prefix: safepaths.SafePath, passphrase: safepaths.SafePath
    ) -> None:
        self._output(
            commands.Argv.of(
                SKOPEO, "generate-sigstore-key", "--passphrase-file", passphrase,
                "--output-prefix", prefix,
            ),
            deadline=defaults.ENGINE_QUERY_DEADLINE,
        )

    def running_containers(self) -> bytes:
        return self._output(
            commands.Argv.of(PODMAN, "ps", "--format", "json"),
            deadline=defaults.ENGINE_QUERY_DEADLINE,
        )

    def _output(self, argv: commands.Argv, *, deadline: timing.Deadline) -> bytes:
        completed = self._processes.run(
            argv, deadline=deadline, limit=commands.OutputLimit.default()
        )
        if not completed.succeeded:
            raise errors.PortFailure(
                port="containers",
                cause=f"{argv.arguments[0]} exited with {completed.exit_code}: "
                f"{completed.stderr.decode(errors='replace').strip()}",
            )
        return completed.stdout
