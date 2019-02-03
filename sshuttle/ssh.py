import sys
import os
import re
import socket
import zlib
import importlib
import subprocess as ssubprocess
import shlex
import sshuttle.helpers as helpers
from sshuttle.helpers import debug2

try:
    # Python >= 3.5
    from shlex import quote
except ImportError:
    # Python 2.x
    from pipes import quote


def readfile(module_name):
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        raise RuntimeError('Unknown module "%s".' % module_name)
    assert isinstance(spec.loader, importlib.abc.InspectLoader)

    body = spec.loader.get_source(module_name)
    assert body is not None
    encoded_body = body.encode('utf-8')
    is_pkg = spec.submodule_search_locations is not None

    return encoded_body, is_pkg

# The complement to empackage() is the parser in StreamImporter() in
# assembler.py.
def empackage(z, name, data, is_pkg):
    if not data:
        data, is_pkg = readfile(name)
    content = z.compress(data)
    content += z.flush(zlib.Z_SYNC_FLUSH)

    return b'%s\n%s\n%d\n%s' % (
        name.encode('utf-8'),
        (b'True' if is_pkg else b'False'),
        len(content),
        content)


def connect(ssh_cmd, rhostport, python, stderr, options):
    portl = []

    if re.sub(r'.*@', '', rhostport or '').count(':') > 1:
        if rhostport.count(']') or rhostport.count('['):
            result = rhostport.split(']')
            rhost = result[0].strip('[')
            if len(result) > 1:
                result[1] = result[1].strip(':')
                if result[1] is not '':
                    portl = ['-p', str(int(result[1]))]
        # can't disambiguate IPv6 colons and a port number. pass the hostname
        # through.
        else:
            rhost = rhostport
    else:  # IPv4
        l = (rhostport or '').rsplit(':', 1)
        rhost = l[0]
        if len(l) > 1:
            portl = ['-p', str(int(l[1]))]

    if rhost == '-':
        rhost = None

    z = zlib.compressobj(1)
    content = readfile('sshuttle.assembler')
    optdata = ''.join("%s=%r\n" % (k, v) for (k, v) in list(options.items()))
    optdata = optdata.encode("UTF8")
    content2 = (empackage(z, 'sshuttle') +
                empackage(z, 'sshuttle.cmdline_options', optdata, False) +
                empackage(z, 'sshuttle.helpers') +
                empackage(z, 'sshuttle.ssnet') +
                empackage(z, 'sshuttle.hostwatch') +
                empackage(z, 'sshuttle.server') +
                b"\n")

    pyscript = r"""
                import sys, os;
                verbosity=%d;
                sys.stdin = os.fdopen(0, "rb");
                exec(compile(sys.stdin.read(%d), "assembler.py", "exec"))
                """ % (helpers.verbose or 0, len(content))
    pyscript = re.sub(r'\s+', ' ', pyscript.strip())

    if not rhost:
        # ignore the --python argument when running locally; we already know
        # which python version works.
        argv = [sys.executable, '-c', pyscript]
    else:
        if ssh_cmd:
            sshl = shlex.split(ssh_cmd)
        else:
            sshl = ['ssh']
        if python:
            pycmd = "'%s' -c '%s'" % (python, pyscript)
        else:
            pycmd = ("P=python3.5; $P -V 2>/dev/null || P=python; "
                     "exec \"$P\" -c %s") % quote(pyscript)
            pycmd = ("exec /bin/sh -c %s" % quote(pycmd))
        argv = (sshl +
                portl +
                [rhost, '--', pycmd])
    (s1, s2) = socket.socketpair()

    def setup():
        # runs in the child process
        s2.close()
    s1a, s1b = os.dup(s1.fileno()), os.dup(s1.fileno())
    s1.close()
    debug2('executing: %r\n' % argv)
    p = ssubprocess.Popen(argv, stdin=s1a, stdout=s1b, preexec_fn=setup,
                          close_fds=True, stderr=stderr)
    os.close(s1a)
    os.close(s1b)
    s2.sendall(content)
    s2.sendall(content2)
    return p, s2
