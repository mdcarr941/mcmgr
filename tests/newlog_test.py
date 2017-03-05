import sys
from mcmgr import Log

def fill_log(l, N):
  for k in range(0, N):
    l.write(str(k))

def print_log(l):
  for k in range(len(l.log)):
    print(k, l.log[k])

l = Log(log_len=50, write_stream=None)
fill_log(l, 42)
#print_log(l)

save = l.read_pos
l.advance_read()
assert l.read_pos == save + 1

save = l.read_pos
l.rewind_read()
assert l.read_pos == save - 1

save = l.read_pos
l.seek_read(10)
l.seek_read(-10)
assert l.read_pos == save

lines = l.list_lines(10)
assert len(lines) == min(10, l.log_len-1)

l.seek_read(10)
prev_lines = l.list_prev_lines(10)
assert len(prev_lines) == min(10, l.log_len-1)

lines = l.list_recent_lines(10)
lines.reverse()
l.read_pos = l.write_pos
l.seek_read(-10)
lines2 = l.list_lines(10)
assert len(lines) == len(lines2)
for n in range(len(lines)):
  assert lines[n] == lines2[n]

lines = l.list_all_lines()
for k in range(len(lines)-1):
  a = int(lines[k])
  b = int(lines[k+1])
  assert a < b
