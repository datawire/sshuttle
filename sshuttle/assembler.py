import sys
import zlib
from importlib import abc
from importlib.machinery import ModuleSpec


class StreamImporter(abc.MetaPathFinder, abc.InspectLoader):
    # Gotchas:
    #
    # - Anything using __path__ will not work
    #   (e.g. `pkgutil.iter_modules()`).
    #
    # - Does not implement ResourceLoader (PEP 302 `.get_data()`).
    #   Note that ResourceLoader is deprecated in Python 3.7 anyway,
    #   in favor of ResourceReader (which we don't implement either).
    #
    # Other than that, ths should be pretty robust to any weird
    # scenarios you throw at it.

    sources = {}

    def __init__(self, reader):
        self.origin = reader.name

        # The following parser is the complement to empackage() in
        # ssh.py.
        z = zlib.decompressobj()
        while True:
            name_bytes = reader.readline().strip()
            if not name_bytes:
                return
            name = name_bytes.decode('utf-8')
            is_pkg = reader.readline().strip().decode('utf-8') == 'True'
            nbytes = int(reader.readline().strip().decode('utf-8'))
            if verbosity >= 2:
                sys.stderr.write('server: assembling %r (%d bytes)\n'
                                 % (name, nbytes))
            body = z.decompress(reader.read(nbytes)).decode('utf-8')
            # And save it to self.sources, for later evaluation at
            # import-time
            self.sources[name] = (is_pkg, body)

    def find_spec(self, fullname, path, target=None):
        if fullname not in self.sources:
            return None
        is_package, _ = self.sources[fullname]
        spec = ModuleSpec(name=fullname, loader=self, origin=self.origin, is_package=is_package)
        spec.has_location = False
        return spec

    def get_source(self, fullname):
        if fullname not in self.sources:
            return None
        _, source = self.sources[fullname]
        return source

    def get_code(self, fullname):
        # Copied from the default InspectLoader.get_code(), but adds
        # the optional 2nd argument to .source_to_code().  Overriding
        # this isn't nescessary to function, but it's nice for
        # debugging.
        source = self.get_source(fullname)
        if source is None:
            return None
        return self.source_to_code(source, "{}:{}.py".format(self.origin, fullname))

sys.meta_path.insert(0, StreamImporter(sys.stdin))
sys.stderr.flush()
sys.stdout.flush()

import sshuttle.helpers
sshuttle.helpers.verbose = verbosity

import sshuttle.cmdline_options as options
from sshuttle.server import main
main(options.latency_control, options.auto_hosts, options.to_nameserver)
