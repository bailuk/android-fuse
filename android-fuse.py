#!/usr/bin/env python3

import os
import re
import subprocess
import logging
import errno
import time
import stat
import math
from datetime import datetime

# On Debian our "fuse" is named "fusepy".
try:
    from fuse import FUSE, FuseOSError, Operations, LoggingMixIn
except:
    from fusepy import FUSE, FuseOSError, Operations, LoggingMixIn



def parse_etype(etype):
    types = { 'c': stat.S_IFCHR,
              'b': stat.S_IFBLK,
              's': stat.S_IFSOCK,
              'p': stat.S_IFIFO,
              'd': stat.S_IFDIR,
              'l': stat.S_IFLNK,
              '-': stat.S_IFREG
            }

    etype = etype.lower()
    if etype in types:
        return types[etype]

    return types['-']


def parse_mode(etype, uperm, gperm, operm):
    mode = parse_etype(etype)
    
    def set_perms(perms, modes):
        # sticky bit and suid bit
        modes.update({'t': stat.S_ISVTX, 's' : stat.S_ISUID})
        m = 0

        for p in perms.lower():
            if p in modes:
                m |= modes[p]

        return m

    mode |= set_perms(uperm, {'r': stat.S_IRUSR, 'w': stat.S_IWUSR, 'x': stat.S_IXUSR})
    mode |= set_perms(gperm, {'r': stat.S_IRGRP, 'w': stat.S_IWGRP, 'x': stat.S_IXGRP})
    mode |= set_perms(operm, {'r': stat.S_IROTH, 'w': stat.S_IWOTH, 'x': stat.S_IXOTH})

    return mode



def gen_ino(path):
    import hashlib
    m = hashlib.md5()
    m.update(path.encode('utf-8'))
    return int(m.hexdigest()[:8], 16)


def to_ints(strings):
    result = []

    for i in strings:
        if len(i) != 0:
            result.append(int(i))

    return result


def to_LOGS(ints):
    link = owner = gowner = size = 0

    if len(ints) == 2:
        owner, gowner = ints
    elif len(ints) == 3:
        owner, gowner, size = ints
    elif len(ints) == 4:
        link, owner, gowner, size = ints

    return (link, owner, gowner, size)


def parse_LOGS(strings):
    ints = to_ints(strings)
    return to_LOGS(ints)


def parse_fix_path(path):
    path = path.strip()

    if len(path) == 0:
        path = "/"

    return path


def parse_fix_ltarget(ltarget):
    ltarget  = ltarget.strip()
    if len(ltarget) == 0:
        ltarget = None
    elif ltarget[0] == '/':
        ltarget = MOUNT_POINT + ltarget

    return ltarget


def parse_names(path):
    ltarget = ''

    if "->" in path:
        path, ltarget = path.split('->')

    return (parse_fix_path(path), parse_fix_ltarget(ltarget))


def parse_time(time_str):
    return time.mktime(time.strptime(time_str, '%Y-%m-%d %H:%M'))


def parse_groups(line):
    pattern = (r''
        '^([-dl])'                  # etype
        '([-a-zA-Z]{3})'            # uperm
        '([-a-zA-Z]{3})'            # gperm
        '([-a-zA-Z]{3})'            # operm
        '\s+(\d+)'                  # [nlink]
        '\s*(\d*)'                  # owner
        '\s*(\d*)'                  # gowner
        '\s+(\d+)'                  # [size]
        '\s+([-0-9]{10} \d\d:\d\d)' # mtime
        '\s+(.*)$')                 # [name][->original]
    m = re.match(pattern, line)

    if m is None or len(m.groups()) != 10:
        return None

    return m.groups()



def parse_ls_line(line):
    g = parse_groups(line)

    if g is None:
        print("Could not parse [{}]".format(line))
        return None

    etype                     =             g[0]
    mode                      = parse_mode(*g[0:4])
    link, owner, gowner, size = parse_LOGS (g[4:8])
    mtime                     = parse_time (g[8]  )
    path, ltarget             = parse_names(g[9]  )

    return {
            'etype'     : etype,
            'st_mode'   : mode,
            'st_uid'    : owner,
            'st_gid'    : gowner,
            'st_mtime'  : mtime,
            'st_size'   : size,
            'st_blksize': 8192,
            'st_blocks' : size//512 + bool(size % 512),
            'path'      : path,
            'ltarget'   : ltarget,
            'st_nlink'  : link,

            # Now, we make up data:
            'st_ino'    : gen_ino(path),
           }


def test_parse_ls_line():
    r = True

    # Some variants of 'ls' print a 'Total ...' line first.
    r = r and parse_ls_line("Total 302") is None


    # There are at least 3 variants of 'ls' output we have to cover.
    r = r and parse_ls_line("drwxr-xr-t 14 100000 100000 653 2018-07-20 03:17 directory") is not None
    r = r and parse_ls_line("drwxr-xr-x 100000 100000 653 2018-07-20 03:17 blah->xyz") is not None
    r = r and parse_ls_line("drwxr-xr-x 100000 100000 2018-07-20 03:17 /") is not None

    # Ignore devices.
    r = r and parse_ls_line("crw-rw-rw- 0 0 1, 5 2020-05-01 13:08 zero") is None
    r = r and parse_ls_line("srwxrwxrwx 1 1003 1004 0 2020-05-05 06:56 /dev/anbox_audio") is None

    return r




def args_shell(args):
    return ADB_ARGS + ['shell'] + args

def args_adb(args):
    return ADB_ARGS + args


def parg(path):
    return "'" + path + "'"


def args_list(args):
    if type(args) is str:
        return args.split(' ')
        
    return args


def args_str(args):
    if type(args) is list:
        return ' '.join(args)
    
    return args
    


def print_header(args):
    print('_________________________________________________')
    print(datetime.now().strftime("%H:%M:%S"))
    print(args_str(args))
    


def rshell(args, w_data = None):
    args = args_shell(args_list(args))
    print_header(args)
    
    if w_data is None:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE)
        r_data = proc.communicate()[0]
    else:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        r_data = proc.communicate(w_data)[0]

    ret = proc.returncode
    return [r_data, ret]

    


def shell_lines(args):
    return rshell(args)[0].decode('utf-8').splitlines()


def shell(args, w_data = None):
    r_data, ret = rshell(args, w_data)

    if ret != 0:
        raise FuseOSError(ret)
        
    return r_data


def print_error(exception):
    e = exception.errno

    if e == errno.ENOTEMPTY:
        print("ENOTEMPTY")
    elif e == errno.ENOENT:
        print("ENOENT")
    elif e == errno.EPERM:
        print("EPERM")


def raise_error(exception = None):
    if not type(exception) is FuseOSError:
        exception = FuseOSError(errno.ENOENT)
        
    print_error(exception)
    raise exception
      
   
def gcd(a, b, c):
    return math.gcd(a, math.gcd(b, c))
       
   
   
class Cache():
    def __init__(self):
        self.cache = {}
       
    def get(self, path):
        if path in self.cache:
            return self.cache[path]
        return None

        
    def put(self, path, r):
        if r is not None:
            self.cache[path] = r
        return r

        
    def pop(self, path):
        if path in self.cache:
            return self.cache.pop(path)
        return None            
        
    
class DoubleCache():
    def __init__(self):
        self.cache_list = Cache()
        self.cache = Cache()


    def remove(self, path):
        self.cache_list.pop(path)
        self.cache.pop(path)       
        
        parent = os.path.dirname(path)
        self.cache_list.pop(parent)
        self.cache.pop(parent)
        
        
    def get(self, path):
        return self.cache.get(path)
        
    def get_list(self, path):
        return self.cache_list.get(path)
                
    def put(self, path, r):
        if type(r) is list:
            self.cache_list.put(path, r)
        elif type(r) is dict:
            self.cache.put(path, r)
    

class IoStub():
    def read(self, path, count, offset):
        raise FuseOSError(errno.ENOENT)
        
        
    def write(self, path, count, offset):
        raise FuseOSError(errno.ENOENT)
    
 
class IoDD():
    def read(self, path, count, offset):
        try:
            bs = gcd(count, offset, 1024);
            args = ['dd','if=' + parg(path), 
                      'bs='    + str(int(bs)),
                      'count=' + str(int(count / bs)), 
                      'skip='  + str(int(offset / bs))]
                          
            return shell(args)

        except Exception as e:
            raise_error(e)


    def write(self, path, data, seek):
        try:
            count = len(data)
            bs = gcd(count, seek, 1024)
            args = ['dd', 'of='    + parg(path), 
                          'bs='    + str(int(bs)), 
                          'count=' + str(int(count/bs)), 
                          'seek='  + str(int(seek/bs))]
                          
            shell(args, data)
            return count
            
        except Exception as e:
            raise_error(e)






def io_factory():
    try:
        d_in = "test\r\n".encode()  
        args = ['dd', 'bs=1', 'count=' + str(len(d_in))] 
        d_out = shell(args, d_in)

        if d_out == d_in:
            return IoDD()
            
        else:
            return IoStub()
            
    except:
        return IoStub()
        
    
class AndroidADBFuse(LoggingMixIn, Operations):
    def __init__(self):
        self.cache = DoubleCache()
        self.io = io_factory()


    def readdir_real(self, path):
        """
            Returns a list of files from 'path'.
            It adds only files from parseable 'ls' lines.
            This is to filter out files that we can't handle.
        """

        result = ['.', '..']

        for line in shell_lines(['ls', '-ln', parg(path)]):
            r = parse_ls_line(line)
            if r is not None and 'path' in r:
                result.append(r['path'])
                self.cache.put(os.path.join(path,r['path']), r)

        self.cache.put(path, result)
        return result



    def readdir(self, path, fh):
        try:
            r = self.cache.get_list(path)
            if r is None:
                r = self.readdir_real(path)
            if r is None:
                raise FuseOSError(errno.ENOENT)
            return r
            
        except Exception as e:
            raise_error(e)
            


    def getattr_real(self, path):
        for line in shell_lines(['ls', '-lnd', parg(path)]):
            r = parse_ls_line(line)

            if r is not None: 
                self.cache.put(path, r)
                return r

        return None;

    

    def getattr(self, path, fh=None):
        try:
            r = self.cache.get(path)
            if r is None:
                r = self.getattr_real(path)
            if r is None:
                raise FuseOSError(errno.ENOENT)
            return r
            
        except Exception as e:
            # Only works correctly with 'ENOENT 2 No such file or directory'
            raise_error(FuseOSError(errno.ENOENT))


    

    def read(self, path, count, offset, fh):
        return self.io.read(path, count, offset)


    def write(self, path, data, seek, fh):
        return self.io.write(path, data, seek)
        self.cache.remove(path)


    def readlink(self, path):
        return self.getattr(path)['ltarget']


    def rmdir(self, path):
        try:
            args = ["rmdir", parg(path)]
            shell(args)
            self.cache.remove(path)
            
        except Exception as e:
            if e.errno == errno.EPERM:
                raise_error(FuseOSError(errno.ENOTEMPTY))
            else:
                raise_error(e)


    def unlink(self, path):
        try:
            args = ['rm', parg(path)]
            shell(args)
            self.cache.remove(path)
            
        except Exception as e:
            raise_error(e)


    def mkdir(self, path, mode):
        try:
            args = ['mkdir', parg(path)]
            shell(args)
            self.cache.remove(path)
            
        except Exception as e:
            raise_error(e)


    def create(self, path, mode, fi=None):
        try:
            args = ['touch', parg(path)]
            shell(args)
            self.cache.remove(path)
            return 0
        except Exception as e:
            raise_error(e)


    def rename(self, old, new):
        try:
            args = ['mv -f ', parg(old), parg(new)]
            shell(args)
            self.cache.remove(old)
            self.cache.remove(new)

        except Exception as e:
            raise_error(e)


    def symlink(self, target, source):
        try:
            args = ['ln', '-s', source, target]
            shell(args)
            self.cache.remove(target)
        except Exception as e:
            raise_error(e)



    def truncate(self, path, length, fh=None): 
        try:
            args = ['truncate', '-s', str(length), path]
            shell(args)
            self.cache.remove(path)
        except Exception as e:
            raise_error(e)


         
    


def init_adb_args(argv):
    global ADB_ARGS

    ADB_ARGS = ['adb']
    if len(argv) > 2:
        ADB_ARGS.extend(argv[2:])


def init_mount_point(argv):
    from sys import exit

    global MOUNT_POINT


    MOUNT_POINT = os.path.abspath(argv[1])
    if MOUNT_POINT[-1] == '/':
        MOUNT_POINT = MOUNT_POINT[:-1]


     
    

def main(argv):
    from sys import exit

    if len(argv) < 2:
        print('usage: {} <mountpoint> [adb_options...]'.format(argv[0]))
        exit(1)

    init_mount_point(sys.argv)
    init_adb_args(sys.argv)

    if not test_parse_ls_line():
        print('ls line parser failed.')
        exit(1)

    logging.getLogger('fuse.log-mixin').setLevel(logging.DEBUG)
    FUSE(AndroidADBFuse(), MOUNT_POINT, foreground=True, nothreads=True, encoding='utf-8')


if __name__ == '__main__':
    print("THIS IS COMPLETELY EXPERIMENTAL SOFTWARE")
    print("IT MAY DELETE DATA, CALL VALUE-ADDED LINES, OR ANYTHING ELSE")
    print("USE AT YOUR OWN RISK\n")
    import sys
    main(sys.argv)

