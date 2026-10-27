"""Fixed cgroup-before-exec trampoline. Only the root controller invokes this.

The fd is opened by the original controller, not supplied by product code.
No product imports or subprocesses occur before containment attachment.
"""
import os
import sys


def main():
    fd = int(sys.argv[1])
    pid = str(os.getpid()).encode()
    if os.write(fd, pid) != len(pid):
        raise OSError('incomplete cgroup attachment')
    os.close(fd)
    if sys.argv[2] != '/usr/bin/bwrap':
        raise SystemExit('unsupported executable')
    os.execv('/usr/bin/bwrap', sys.argv[2:])


if __name__ == '__main__':
    main()
