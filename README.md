# Android-fuse

Mounts an android device using FUSE.

Requires [fusepy](https://github.com/terencehonles/fusepy) and that `adb` be
present in the PATH.

This works by calling `adb shell ls`, `adb shell ln`, `adb shell mv`, 
`adb shell rm`, `adb shell rmdir`, `adb shell mkdir` and 
`adb shell touch` to manipulate the file system. 
It calls `adb shell dd` to read and write from and to files.

Usage:

    python3 android-fuse.py <mount-point> [adb_options...]

THIS IS ALPHA SOFTWARE AND MAY DO BAD THINGS TO YOUR PHONE, INCLUDING
DESTROYING DATA!

This rewrite of the [original version of fuse-py](https://github.com/luispedro/android-fuse)
uses `adb shell dd` to read and write directly from an to files on the android device.

THIS IS VERY EXPERIMENTAL SOFTWARE AND IT IS ONLY TESTET WITH A FEW DEVICES

# What works & what does not

- You can list directories and 'cd' into them
- You can read from files on the phone, including symlinks
- You can write to files on the phone, including symlinks
- `du -sh somefile.txt` will work as expected
- You can delete files from the phone
- You can create files and directories
- You can create symlinks on the device


Licence: MIT  
Original author: [Luis Pedro Coelho](http://luispedro.org) [luis@luispedro.org](mailto:luis@luispedro.org)  
Author: [Lukas Bai](mailto:bailu@bailu.ch)

