"""Explicit workspace context. Linux Landlock is mandatory for public execution.

The kernel boundary also applies to subprocesses and prevents path-check/use escapes.
It does not replace document authorization, no-clobber publication or fidelity checks.
"""
import ctypes
import errno
import os
from pathlib import Path
import sys

SKILL_ROOT = Path(__file__).resolve().parents[1]
_WORKSPACE = None

def _landlock(workspace, workspace_fd):
    if sys.platform != 'linux':
        raise RuntimeError('Secure workspace execution currently requires Linux Landlock')
    libc = ctypes.CDLL(None, use_errno=True)
    def call(number, *args):
        value = libc.syscall(number, *args)
        if value < 0:
            raise OSError(ctypes.get_errno(), 'Landlock unavailable or denied; no unsafe fallback')
        return value
    # Linux generic syscall numbers on the explicitly supported architectures.
    import platform
    if platform.machine() not in ('x86_64', 'aarch64'):
        raise RuntimeError('Unsupported Landlock architecture')
    abi = call(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError('Landlock ABI >= 3 is required (truncate protection)')
    class Ruleset(ctypes.Structure):
        _fields_ = [('handled_access_fs', ctypes.c_uint64)]
    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int)]
    handled = (1 << 15) - 1
    read = (1 << 0) | (1 << 2) | (1 << 3)
    ruleset = call(444, ctypes.byref(Ruleset(handled)), ctypes.sizeof(Ruleset), 0)
    def grant(path, access):
        if not path.exists():
            return
        fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            # Files cannot receive directory-only access bits.
            mask = access if path.is_dir() else access & ((1 << 0) | (1 << 1) | (1 << 2) | (1 << 14))
            call(445, ruleset, 1, ctypes.byref(Rule(mask, fd)), 0)
        finally:
            os.close(fd)
    try:
        for p in [SKILL_ROOT, Path(sys.prefix), Path(sys.base_prefix), Path('/usr'), Path('/lib'), Path('/lib64'), Path('/etc'), Path('/proc'), Path('/sys'), Path('/var/cache/fontconfig')]:
            grant(p, read)
        # Installed user fonts are read-only resources, never host config/credentials.
        for folder in [Path.home()/'.local/share/fonts', Path.home()/'.fonts']:
            if folder.is_dir() and not folder.is_symlink():
                grant(folder, 1 << 3)  # enumerate fonts, not arbitrary file contents
                for font in folder.rglob('*'):
                    if font.suffix.lower() in ('.ttf', '.otf', '.ttc') and font.is_file() and not font.is_symlink():
                        grant(font, 1 << 2)
        # Runtime devices only; no HOME or arbitrary user-directory access.
        for p in ['/dev/null', '/dev/urandom', '/dev/random']:
            grant(Path(p), (1 << 1) | (1 << 2))
        call(445, ruleset, 1, ctypes.byref(Rule(handled, workspace_fd)), 0)
        # /tmp is writable ONLY if a private mount namespace maps it to a
        # pinned directory inside this workspace; the host /tmp is never granted.
        alias = os.environ.get('XJTU_RENDER_TMP')
        if alias:
            target = Path(alias).resolve(strict=True)
            if not target.is_relative_to(workspace) or not target.name.startswith('.render-ipc-') or not os.path.samestat(target.stat(), Path('/tmp').stat()):
                raise ValueError('Invalid private renderer /tmp mount')
            grant(Path('/tmp'), handled)
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'Cannot set no_new_privs')
        call(446, ruleset, 0)
    finally:
        os.close(ruleset)

def _require_workspace_policy():
    """SkillHub public builds require valid policy even when legacy env is set."""
    import json, stat
    expected = {'schema_version': '1.0', 'require_explicit_workspace': True,
                'allow_legacy_test_fallback': False}
    try:
        fd = os.open(SKILL_ROOT/'WORKSPACE-REQUIRED.json',
                     os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            st = os.fstat(stream.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size > 4096:
                raise ValueError('Invalid policy file type or size')
            policy = json.loads(stream.read(4097))
        if (not isinstance(policy, dict) or policy.keys() != expected.keys()
                or any(type(policy[k]) is not type(v) or policy[k] != v
                       for k, v in expected.items())):
            raise ValueError('Public workspace policy cannot be weakened')
    except (OSError, ValueError, UnicodeError) as exc:
        raise RuntimeError('Missing or invalid WORKSPACE-REQUIRED.json; execution refused') from exc

def _initialize():
    global _WORKSPACE
    _require_workspace_policy()
    if '--workspace' not in sys.argv:
        if '--help' in sys.argv or '-h' in sys.argv:
            return
        raise RuntimeError('Explicit --workspace /authorized/existing/directory required; install directory is read-only')
    i = sys.argv.index('--workspace')
    if i + 1 >= len(sys.argv):
        raise ValueError('--workspace requires an existing directory')
    raw = Path(sys.argv[i+1]).absolute()
    if '..' in raw.parts:
        raise ValueError('Parent traversal is forbidden')
    for p in [raw, *raw.parents]:
        if p.is_symlink():
            raise ValueError('Workspace symlinks are forbidden')
    workspace = raw.resolve(strict=True)
    if not workspace.is_dir() or workspace.is_relative_to(SKILL_ROOT) or SKILL_ROOT.is_relative_to(workspace):
        raise ValueError('Workspace must be separate from the installation tree')
    if workspace == Path.home() or any(x in workspace.parts for x in ('.agents', '.claude', '.opencode', '.codex', '.ssh', '.aws')):
        raise ValueError('Do not use HOME or host/credential directories as workspaces')
    del sys.argv[i:i+2]
    # Current public CLIs accept only path-valued positional/options (plus flags).
    # Validate explicit inputs before library/system read exceptions are granted.
    for arg in sys.argv[1:]:
        if arg.startswith('-') and '=' not in arg:
            continue
        value = arg.split('=', 1)[1] if arg.startswith('-') else arg
        candidate = Path(value)
        if '..' in candidate.parts:
            raise ValueError('Parent traversal is forbidden')
        candidate = (workspace/candidate).resolve()
        if not candidate.is_relative_to(workspace) and not any(candidate.is_relative_to(SKILL_ROOT/x) for x in ('assets', 'references')):
            raise ValueError('CLI file access must remain in workspace or installed rule/assets resources')
    # Pin every workspace component without following symlinks. A swap before
    # restriction must never grant a different path via a second pathname lookup.
    fd = os.open('/', os.O_PATH | os.O_DIRECTORY)
    try:
        for part in workspace.parts[1:]:
            child = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or st.st_mode & 0o022:
            raise ValueError('Workspace must be owned by this user and not group/world writable')
        if Path(sys.argv[0]).name == 'render_docx.py' and not os.environ.get('XJTU_RENDER_TMP'):
            # Enter a private mount namespace before applying Landlock. Pin both
            # bind sources by FD, so pathname swaps cannot grant another directory.
            import shutil, uuid
            bwrap = shutil.which('bwrap')
            if not bwrap:
                raise RuntimeError('Private PDF renderer requires installed bubblewrap')
            name = '.render-ipc-' + uuid.uuid4().hex
            os.mkdir(name, 0o700, dir_fd=fd)
            temp_fd = os.open(name, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.set_inheritable(fd, True)
            os.set_inheritable(temp_fd, True)
            command = [bwrap, '--die-with-parent', '--new-session', '--unshare-user', '--unshare-pid', '--unshare-net',
                       '--ro-bind', '/', '/', '--bind', '/proc/self/fd/'+str(fd), str(workspace),
                       '--bind', '/proc/self/fd/'+str(temp_fd), '/tmp', '--proc', '/proc', '--dev', '/dev',
                       '--chdir', str(workspace), '--setenv', 'XJTU_RENDER_TMP', str(workspace/name),
                       '--', sys.executable, '-B', str(Path(sys.argv[0]).resolve()), *sys.argv[1:],
                       '--workspace', str(workspace)]
            os.execv(bwrap, command)
        _landlock(workspace, fd)
    finally:
        os.close(fd)
    _WORKSPACE = workspace
    os.chdir(workspace)
    # Explicitly keep runtime caches and subprocess state inside the workspace.
    runtime = workspace/'.xjtu-runtime'
    runtime.mkdir(exist_ok=True)
    for name in ('TMPDIR', 'TMP', 'TEMP', 'XDG_CACHE_HOME', 'MPLCONFIGDIR'):
        os.environ[name] = str(runtime)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True

_initialize()

def data_root():
    return _WORKSPACE or SKILL_ROOT

def output_root(role):
    roles={'format','render','pagination','figures','polishing','mapping',
           'polishing_writer','workflow','experiment_report'}
    if role not in roles:
        raise ValueError('Unknown output role')
    if _WORKSPACE is not None:
        return _WORKSPACE
    if '--help' in sys.argv or '-h' in sys.argv:
        return Path(os.devnull)  # import-only sentinel; CLI exits without writing
    raise RuntimeError('Authorized workspace required for output')

def publish_text(path, text):
    """No-clobber atomic text publication, including concurrent report writers."""
    import tempfile
    path = Path(path)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, path)
    finally:
        os.unlink(name)


def check_input(path):
    """Validate paths discovered inside JSON, independently of CLI arguments."""
    p = Path(path).resolve()
    if _WORKSPACE is not None and not p.is_relative_to(_WORKSPACE) and not any(p.is_relative_to(SKILL_ROOT/x) for x in ('assets', 'references')):
        raise ValueError('Unauthorized input path')
    return p
