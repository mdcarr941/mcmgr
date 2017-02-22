#!/usr/bin/python3

import shutil
import signal
import sys
import time

def sighandler(a,b):
  sys.exit(0)

signal.signal(signal.SIGTERM, sighandler)
signal.signal(signal.SIGINT, sighandler)

f = open('/dev/stdout', 'wb')
A = bytes('A', 'ascii')
B = bytes('B', 'ascii')
esc = b'\x1b'
#reset = esc + bytes('[2J', 'ascii')
reset = esc + bytes('[0;0H', 'ascii')

sz = shutil.get_terminal_size((80,20))
total_chars = (sz.lines - 1) * sz.columns
out = A * total_chars + bytes('\nLine written', 'ascii')
f.write(out)
f.flush()
for k in range(1,10):
  time.sleep(0.5)
  f.write(reset)
  if k % 2 == 0:
    out = A * total_chars
  else:
    out = B * total_chars
  out += bytes('\nLine written', 'ascii')
  f.write(out)
  f.flush()
f.write(bytes('\n', 'ascii'))

f.close()
