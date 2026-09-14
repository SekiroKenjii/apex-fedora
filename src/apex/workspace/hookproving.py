"""Disposable repositories asked what the three git checks state, through a real Git.

The hooks are proven as the older tree proved them: on repositories made for the purpose
under the runtime root, with a fixture identity and none of the operator's configuration,
and the answers judged on the host. Each check is a list of questions and the answer the
rules must give; the hook's answer to every question goes into the check's report, and a
report in which every answer is the expected one is the check's pass. The hook is handed
in, because the kinds that answer to Git are declared above this layer.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path

from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, refusals, safepaths, verdicts
from apex.ports import files, process
from apex.workspace import rulespecs

type Inspect = Callable[[str, Path, Sequence[str], str], Sequence[rulespecs.Finding]]

COMMIT_MSG = "commit-msg"
PRE_COMMIT = "pre-commit"
PRE_PUSH = "pre-push"
COMMIT_POLICY = identifiers.CheckId("git.commit-policy")
PRIVATE_STAGE = identifiers.CheckId("git.private-stage")
OUTGOING_HISTORY = identifiers.CheckId("git.outgoing-history")
BRANCH = "refs/heads/main"
ABSENT = "0" * 40
UNFETCHED = "c" * 40
SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"
FIRST_SUBJECT = "feat(src): the first file"
IDENTITY = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "apex",
    "GIT_AUTHOR_EMAIL": "apex@localhost",
    "GIT_COMMITTER_NAME": "apex",
    "GIT_COMMITTER_EMAIL": "apex@localhost",
}
MESSAGES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("a conventional subject", f"{FIRST_SUBJECT}\n", ()),
    ("a subject without a type", "bad subject\n", ("commit.subject-malformed",)),
    ("a type the policy does not know", "wip: something\n", ("commit.subject-malformed",)),
    ("a subject past the limit", "feat(src): " + "x" * 70 + "\n", ("commit.subject-too-long",)),
    ("a body under the subject", "feat(src): ok\n\nA body line.\n", ("commit.has-body",)),
    (
        "a co-author trailer",
        "feat(src): ok\n\nCo-authored-by: Someone <someone@localhost>\n",
        ("commit.co-author-trailer",),
    ),
    ("a carriage return", "feat(src): ok\r\n", ("commit.carriage-return",)),
)
STAGED: tuple[tuple[str, str, bytes, tuple[str, ...]], ...] = (
    ("a clean file", "src/b.py", b"value = 2\n", ()),
    ("a private document", ".env", b"A=1\n", ("repository.private-document",)),
    (
        "a private key",
        "notes.txt",
        b"-----BEGIN " + b"PRIVATE KEY-----\nsecret\n",
        ("repository.pem-private-key",),
    ),
    (
        "a local-only document under another name",
        "notes.md",
        b"<!-- apex-" + b"local-only -->\nkept local\n",
        ("repository.local-only-content",),
    ),
    ("an opaque binary", "blob.bin", b"\x00\x01\x02", ("repository.blob-contains-nul",)),
)


@dataclasses.dataclass(frozen=True, slots=True)
class Answer:
    """One question, the rules it had to name, and the rules the hook named."""

    question: str
    expected: tuple[str, ...]
    found: tuple[str, ...]

    @property
    def met(self) -> bool:
        if not self.expected:
            return not self.found
        return set(self.expected) <= set(self.found)

    def document(self) -> encoding.Document:
        return {
            "question": self.question,
            "expected": list(self.expected),
            "found": list(self.found),
            "met": self.met,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class Proven:
    check: identifiers.CheckId
    verdict: verdicts.Verdict
    observations: encoding.Document


def proven(check: identifiers.CheckId, repository: Path, answers: Sequence[Answer]) -> Proven:
    verdict = verdicts.PASSED if all(item.met for item in answers) else verdicts.FAILED
    return Proven(
        check=check,
        verdict=verdict,
        observations={
            "check": str(check),
            "repository": str(repository),
            "answers": [item.document() for item in answers],
        },
    )


@dataclasses.dataclass(frozen=True, slots=True)
class Bench:
    """Where the repositories are made, and the hook that answers for each kind."""

    processes: process.ProcessPort
    filesystem: files.FileSystemPort
    scratch: safepaths.SafePath
    inspect: Inspect

    def git(self, repository: Path, *arguments: str, stdin: bytes | None = None) -> str:
        completed = self.processes.run(
            commands.Argv.of("git", "-C", str(repository), *arguments),
            deadline=defaults.HOOK_GIT_DEADLINE,
            limit=commands.OutputLimit.default(),
            stdin=stdin,
            variables=IDENTITY,
        )
        if not completed.succeeded:
            raise errors.Refusal(
                refusals.RefusalReason.HOOK_GIT_FAILED,
                subject=f"git {arguments[0]} exited {completed.exit_code}: "
                f"{completed.stderr.decode(errors='replace').strip()}",
            )
        return completed.stdout.decode(errors="replace").strip()

    def repository(self, name: str) -> Path:
        """A repository with one clean commit, so every question starts from a permitted history."""
        checkout = self.scratch / name
        self.filesystem.make_directory(checkout, mode=safepaths.PRIVATE_DIRECTORY_MODE)
        self.git(checkout.path, "init", "-q", "-b", "main")
        self.commit(checkout.path, "src/a.py", b"value = 1\n", FIRST_SUBJECT)
        return checkout.path

    def write(self, repository: Path, relative: str, payload: bytes) -> None:
        self.filesystem.write_atomic(
            safepaths.SafePath(repository / relative), payload, mode=defaults.RECORD_MODE
        )

    def stage(self, repository: Path, relative: str, payload: bytes) -> None:
        self.write(repository, relative, payload)
        self.git(repository, "add", relative)

    def commit(self, repository: Path, relative: str, payload: bytes, subject: str) -> None:
        self.stage(repository, relative, payload)
        self.git(repository, "commit", "-q", "-m", subject)

    def ask(
        self,
        hook: str,
        repository: Path,
        question: str,
        expected: Sequence[str],
        *,
        arguments: Sequence[str] = (),
        standard_input: str = "",
    ) -> Answer:
        """The hook's answer as rule names; a refusal it raised instead is named the same way."""
        try:
            found = tuple(
                str(item.rule) for item in self.inspect(hook, repository, arguments, standard_input)
            )
        except errors.Refusal as refusal:
            found = (refusal.reason.value,)
        return Answer(question=question, expected=tuple(expected), found=found)


type Prover = Callable[[Bench], Proven]


def commit_policy(bench: Bench) -> Proven:
    """Every message the policy states, written to a file and handed to the commit-msg hook."""
    repository = bench.repository("commit-policy")
    answers = []
    for index, (question, message, expected) in enumerate(MESSAGES):
        relative = f"message-{index}.txt"
        bench.write(repository, relative, message.encode())
        answers.append(
            bench.ask(
                COMMIT_MSG, repository, question, expected, arguments=(str(repository / relative),)
            )
        )
    return proven(COMMIT_POLICY, repository, answers)


def private_stage(bench: Bench) -> Proven:
    """Each staged entry the check names, judged alone in the index and then unstaged."""
    repository = bench.repository("private-stage")
    answers = []
    for question, relative, payload, expected in STAGED:
        bench.stage(repository, relative, payload)
        answers.append(bench.ask(PRE_COMMIT, repository, question, expected))
        bench.git(repository, "reset", "-q")
    blob = bench.git(repository, "hash-object", "-w", "--stdin", stdin=b"src/a.py")
    head = bench.git(repository, "rev-parse", "HEAD")
    for question, entry, rule in (
        ("a symlink entry", f"{SYMLINK_MODE},{blob},link", "repository.entry-is-a-symlink"),
        ("a submodule entry", f"{GITLINK_MODE},{head},sub", "repository.entry-not-regular"),
    ):
        bench.git(repository, "update-index", "--add", "--cacheinfo", entry)
        answers.append(bench.ask(PRE_COMMIT, repository, question, (rule,)))
        bench.git(repository, "reset", "-q")
    return proven(PRIVATE_STAGE, repository, answers)


def _update(local: str, remote: str) -> str:
    return f"{BRANCH} {local} {BRANCH} {remote}\n"


def outgoing_history(bench: Bench) -> Proven:
    """A history with a malformed subject and a private file since removed, pushed four ways."""
    repository = bench.repository("outgoing-history")
    base = bench.git(repository, "rev-parse", "HEAD")
    bench.commit(repository, "src/c.py", b"value = 3\n", "bad subject")
    bench.commit(repository, ".env.local", b"A=1\n", "chore(env): a private file")
    bench.git(repository, "rm", "-q", ".env.local")
    bench.git(repository, "commit", "-q", "-m", "chore(env): the private file removed")
    head = bench.git(repository, "rev-parse", "HEAD")
    pushes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        (
            "the commits a push would send",
            _update(head, base),
            ("commit.subject-malformed", "repository.environment-file"),
        ),
        ("a branch created from the clean base", _update(base, ABSENT), ()),
        ("a branch deleted", _update(ABSENT, head), ()),
        (
            "a remote commit never fetched",
            _update(head, UNFETCHED),
            (refusals.RefusalReason.REPOSITORY_HISTORY_NOT_FETCHED.value,),
        ),
    )
    answers = [
        bench.ask(
            PRE_PUSH,
            repository,
            question,
            expected,
            arguments=("origin", str(repository)),
            standard_input=update,
        )
        for question, update, expected in pushes
    ]
    return proven(OUTGOING_HISTORY, repository, answers)
