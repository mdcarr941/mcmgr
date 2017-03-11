import sys
import os
import threading
import select
import signal
import socket
import subprocess
import logging

logger = logging.getLogger('mcmgr.lineharness')



class StopLogException(Exception):
  """Exception thrown by a LineParser to signal a Log to stop."""
  pass



class LineParser():
  """Parse the lines written to a Log."""


  def mutator(self, line):
    return line


  def parse(self, line):
    return None



class Log(threading.Thread):
  """A class containing the lines output by a subprocess."""
  # The stream object that the log will read from.
  read_stream = sys.stdin
  # The stream object the log will write to.
  write_streams = [sys.stdout]
  ctrl_streams = []
  log_len = 4096
  line_parser = None
  read_wait = 0.1
  advance_flag = False
  write_pos = 0
  read_pos = 0


  def __init__(self, name=None, **kwargs):
    super(Log, self).__init__(daemon=True, name=name)

    for kw in kwargs:
      if kw in dir(self):
        self.__setattr__(kw, kwargs[kw])

    if self.line_parser == None:
      self.line_parser = LineParser()

    if 'log' not in dir(self):
      self.log = [None]
      self.log *= self.log_len
    if len(self.log) != self.log_len:
      raise Exception('Invalid arguments: log_len != len(log)')

    self.running = False
    return


  def start(self, read_stream=None, write_streams=None, ctrl_streams=None):
    if read_stream != None:
      self.read_stream = read_stream
    if write_streams != None:
      self.write_streams = write_streams
    if ctrl_streams != None:
      self.ctrl_streams = ctrl_streams
    self.running = True

    super(Log, self).start()
    return


  def do_read(self):
    try:
      line = self.read_stream.readline()
      if len(line) == 0:
        raise StopLogException
      self.write(line)
    except (ValueError, OSError) as e:
      logger.info('an exception occured in do_read')
      logger.debug(e)
      raise StopLogException
    return


  def run(self):
    logger.debug('entering Log.run')
    while self.running:
      try:
        self.do_read()
      except StopLogException:
        break
    self.running = False
    logger.debug('exiting Log.run')
    return


  def stop(self, *args):
    self.running = False
    return


  def __iter__(self):
    return self


  def __next__(self):
    if self.read_pos == self.write_pos:
      raise StopIteration
    out = self.log[self.read_pos]
    self.read_pos = (self.read_pos + 1) % self.log_len
    return out


  def list_newlines(self):
    return [line for line in self]


  def write_line(self, line):
    if line == None:
      return
    line = self.line_parser.mutator(line)
    message = self.line_parser.parse(line)
    self.log[self.write_pos] = line
    self.advance_write()

    if message != None:
      for stream in self.ctrl_streams:
        try:
          stream.write(str(message))
          stream.flush()
        except (ValueError, OSError):
          continue

    for stream in self.write_streams:
      try:
        stream.write(line)
        stream.flush()
      except (ValueError, OSError):
        continue
    return


  def write(self, lines):
    if type(lines) == type(list()):
      for line in lines:
        self.write_line(line)
    else:
      self.write_line(lines)
    return


  def advance_write(self):
    self.write_pos = (self.write_pos + 1) % self.log_len

    if self.advance_flag:
      if self.write_pos == self.read_pos:
        self.read_pos = (self.read_pos + 1) % self.log_len
      else:
        self.advance_flag = False

    if (self.read_pos - self.write_pos) % self.log_len == 1:
      # We're about to write past the reading pointer, so it should be advanced
      # next time. We set a flag to indicate this.
      self.advance_flag = True
    return


  def go_forward(self, start=None):
    end = self.write_pos
    if start == None:
      start = self.read_pos
    n = start
    yield n
    n = (n + 1) % self.log_len
    while n != end:
      yield n
      n = (n + 1) % self.log_len


  def go_backward(self, start=None):
    end = self.write_pos
    if start == None:
      start = (end - 1) % self.log_len
    n = start
    yield n
    n = (n - 1) % self.log_len
    while n != end:
      yield n
      n = (n - 1) % self.log_len


  def most_recent_read(self):
    """Set read_pos to the most recent line in the log."""
    self.read_pos = (self.write_pos - 1) % self.log_len
    return


  def seek_read(self, num):
    if num < 0:
      num = -num
      gen = self.go_backward(start=self.read_pos)
    else:
      gen = self.go_forward()
    count = 0
    for k in gen:
      count += 1
      if count > num:
        break
    self.read_pos = k
    return


  def rewind_read(self):
    self.seek_read(-1)
    return


  def advance_read(self):
    self.seek_read(1)
    return


  def list_lines_gen(self, gen, num=None, start=None):
    lines = []
    for n in gen(start=start):
      line = self.log[n]
      if line == None:
        break
      lines.append(line)
      if len(lines) == num:
        break
    return lines


  def list_lines(self, num):
    """Get n lines starting at read_pos. Function does not update read_pos. If
       there are fewer than n lines, return them all."""
    return self.list_lines_gen(self.go_forward, num=num)


  def list_prev_lines(self, num):
    """Get a list of n lines starting from read_pos and going backwards. The
       list is ordered from most newest to oldest (so that the line pointed
       to by read_pos is first). If there are fewer than n lines then all are
       returned."""
    return self.list_lines_gen(self.go_backward, num=num, start=self.read_pos)


  def list_recent_lines(self, num):
    """Get the num most recent lines in the log, in order of newest to oldest.
       If there are fewer than n lines, return them all."""
    return self.list_lines_gen(self.go_backward, num=num)


  def get_oldest_index(self):
    """Find the index of the oldest line in the log. This is accomplished by
       starting ahead of the newest line and advancing until we reach an index
       which has an entry."""
    for k in self.go_forward(start=self.write_pos):
      if self.log[k] != None:
        break
    return k


  def list_all_lines(self):
    """Get all lines in the log starting from the oldest. This function
       advances read_pos."""
    lines = self.list_lines_gen(self.go_forward, start=self.get_oldest_index())
    self.read_pos = self.write_pos
    return lines


  def __str__(self):
    lines = self.list_all_lines()
    return ''.join(lines)



class Server(threading.Thread):
  # Number of seconds to wait for subprocess to exit.
  sub_timeout = 30
  line_parser = LineParser()


  def __init__(self, name, **kwargs):
    super(Server, self).__init__(name=name + '-Server')

    for kw in kwargs:
      if kw in dir(self):
        self.__setattr__(kw, kwargs[kw])
    assert 'mcserver' in dir(self)

    self.log = Log(name=name + '-Log', line_parser=self.line_parser)

    if 'address' not in dir(self):
      self.address = self.name + '.sock'
    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    self.timeout = .05
    self.sock.settimeout(self.timeout)
    self.running = False
    self.returncode = None
    self.sub = None
    return


  def start(self):
    def replace_handler():
      # Ignore SIGINT. The parent will handle this signal for the child.
      signal.signal(signal.SIGINT, signal.SIG_IGN)

    self.sub = subprocess.Popen(self.cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, cwd=self.cwd,
                                bufsize=1, universal_newlines=True,
                                preexec_fn=replace_handler)
    self.running = True
    self.log.start(read_stream=self.sub.stdout, ctrl_streams=[self.sub.stdin])
    try:
      self.sock.bind(self.address)
    except OSError:
      logger.error('Address already in use: ' + self.address)
      self.stop()
      return
    self.sock.listen()
    super(Server, self).start()
    return


  def respond(self, connection):
    return


  def run(self):
    while self.sub.poll() == None:
      try:
        connection, client_addr = self.sock.accept()
      except socket.timeout:
        continue
      self.respond(connection)

    self.stop()
    return


  def stop_sub(self):
    self.sub.terminate()
    out, err = self.sub.communicate(timeout=self.sub_timeout)
    return


  def stop(self, *args):
    if self.running:
      self.running = False
      out = None
      try:
        self.stop_sub()
      except subprocess.TimeoutExpired:
        logger.warning('Timeout for subprocess exit has expired, '
                        + 'sending the kill signal.')
        self.sub.kill()
      self.log.write(out)
    self.log.stop()

    try:
      os.unlink(self.address)
    except FileNotFoundError:
      pass

    if self.sub.returncode != None:
      self.returncode = self.sub.returncode

    return
