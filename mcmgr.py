#!/usr/bin/python3
WORLDS_DIR = os.path.join(os.environ['HOME'], 'worlds')
MCSERVER = os.path.join(os.environ['HOME'], 'mcservers', 'minecraft_server.jar')
MEMSTART = '256M'
MEMMAX = '1G'
LOGFILE = 'mcmgr.log'

import sys
import os
import subprocess
import time
import socket
import threading
import select
import random
import logging
import curses
from curses import ascii

logging.basicConfig(filename=LOGFILE, level=logging.INFO)

class StopLogException(Exception):
  pass

class Log(threading.Thread):
  """A class containing the lines output by a subprocess."""
  # The stream object that the log will read from.
  read_stream = sys.stdin
  # The stream object the log will write to.
  write_stream = sys.stdout
  ctrl_stream = None
  log_len = 4096
  line_parser = None
  read_wait = 0.1

  # A selector object used to do asynchronous IO.
  selector = None
  # Should read_pos be advanced?
  advance_flag = False
  log = [None]
  write_pos = 0
  read_pos = 0
  running = False


  def __init__(self, name=None, **kwargs):
    super(Log, self).__init__(target='daemon', name=name)

    for kw in kwargs:
      if kw in dir(self):
        self.__setattr__(kw, kwargs[kw])

    if self.line_parser == None:
      self.line_parser = LineParser()

    if len(self.log) == 1:
      self.log *= self.log_len
    if len(self.log) != self.log_len:
      raise Exception('Invalid arguments: log_len != len(log)')

    return


  def write(self, line):
    if line == None:
      return

    line = self.line_parser.mutator(line)

    try:
      message = self.line_parser.parse(line)
    except StopLogException:
      self.stop()
      return

    if message != None and self.ctrl_stream != None\
                       and not self.ctrl_stream.closed:
      self.ctrl_stream.write(str(message))

    if self.write_stream != None and not self.write_stream.closed:
      self.write_stream.write(line)

    self.log[self.write_pos] = line
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


  def most_recent_read(self):
    """Set read_pos to the most recent line in the log."""
    self.read_pos = (self.write_pos - 1) % self.log_len
    return


  def rewind_read(self):
    """Move read_pos backwards, whilst keeping it ahead of write_pos."""
    prev = (self.read_pos - 1) % self.log_len
    if (self.write_pos - prev) % self.log_len != 1:
      self.read_pos = prev
    return


  def advance_read(self):
    """Move read_pos forward, whilst still keeping it behind write_pos."""
    nxt = (self.read_pos + 1) % self.log_len
    if nxt != self.write_pos:
      self.read_pos = nxt
    return


  def seek_read(self, n):
    """Seek read_pos according to the integer n. If n is positive
       advance the read pointer n times, if n is negative rewind it n times.
       This implementation is not very efficient, but should be reliable."""
    if n < 0:
      f = self.rewind_read
      n = -n
    else:
      f = self.advance_read
    for k in range(n):
      f()
    return


  def start(self, read_stream=None, write_stream=None, ctrl_stream=None):
    if read_stream != None:
      self.read_stream = read_stream
    if write_stream != None:
      self.write_stream = write_stream
    if ctrl_stream != None:
      self.ctrl_stream = ctrl_stream
    self.running = True

    super(Log, self).start()
    return


  def run(self):
    logging.debug('entering Log.run')
    while self.running and not self.read_stream.closed:
      try:
        rlist, _, _ = select.select([self.read_stream], [], [], self.read_wait)
        for fileobj in rlist:
          line = fileobj.readline()
          if len(line) == 0:
            self.running = False
            break
          self.write(line)
      except OSError or ValueError:
        break
    self.running = False
    logging.debug('exiting Log.run')
    return


  def stop(self):
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


  def get_oldest_index(self):
    """Find the index of the oldest line in the log. This is accomplished by
       starting ahead of the newest line and advancing until we reach an index
       which has an entry."""
    # Save a copy of write_pos in case it changes.
    start = self.write_pos
    oldest = start 
    while self.log[oldest] == None:
      oldest = (oldest + 1) % self.log_len
      if oldest == start:
        break
    return oldest


  def list_all_lines(self):
    """Get all lines in the log starting from the oldest. This function
       advances read_pos."""
    pos = self.get_oldest_index()
    end = self.write_pos
    lines = []
    while pos != end:
      lines.append(self.log[pos])
      pos = (pos + 1) % self.log_len
    self.read_pos = end
    return lines


  def __str__(self):
    lines = self.list_all_lines()
    return ''.join(lines)


  def list_newlines(self):
    return [line for line in self]


  def list_lines(self, n):
    """Get n lines starting at read_pos. Function does not update read_pos. If
       there are fewer than n lines, return them all."""
    lines = []
    for k in range(n):
      lines.append(self.log[(self.read_pos + k) % self.log_len])
    return lines


  def list_prev_lines(self, n):
    """Get a list of n lines starting from read_pos and going backwards. The
       list is ordered from most newest to oldest (so that the line pointed
       to by read_pos is first). If there are fewer than n lines then all are
       returned."""
    lines = []
    pos = self.read_pos
    for k in range(n):
      if self.log[pos] == None:
        break
      lines.append(self.log[pos])
      pos = (pos - 1) % self.log_len
    return lines


  def go_backwards(self):
    n = self.write_pos - 1
    while True:
      yield self.log[n]
      n = (n-1) % self.log_len


  def list_recent_lines(self, n):
    """Get the n most recent lines in the log, in order of newest to oldest.
       If there are fewer than n lines, return them all."""
    lines = []
    for line in self.go_backwards():
      lines.append(line)
      if len(lines) == n:
        break;
    return lines



class LineParser():

  def __init__(self):
    random.seed()
    return


  def mutator(self, line):
    return line


  def parse(self, line):
    """Extract player_name and pass on the remainder of the line 
       to another method."""
    lb = rb = n = 0
    for n in range(len(line)):
      c = line[n]
      if c == '[':
        lb += 1
      elif c == ']':
        rb += 1
      if lb == 2 and rb == 2:
        break

    tokens = line[n+2:].lstrip().split()
    if len(tokens) > 0:
      logging.debug('tokens = ' + str(tokens))
      
    if len(tokens) < 2:
      return

    char = tokens[0][0]
    if char == '<' or char == '[':
      char2 = chr(ord(char)+2)
      player_name = tokens[0].lstrip(char).rstrip(char2)
    else:
      return

    if tokens[1] in dir(self):
      method = self.__getattribute__(tokens[1])
      return method(*tokens[2:], player_name=player_name) + '\n'


  def say_randint(self, *args, **kwargs):
    """Generate a random integer N such that 1 <= N <= b."""
    b = args[0] 
    cmd = '/say '
    try:
      b = int(b)
      cmd += str(random.randint(1, b))
    except ValueError:
      cmd += 'ValueError: expected an integer'
    return cmd


  def admonish(self,*args, **kwargs):
    target = args[0]
    try:
      player_name = kwargs['player_name']
    except KeyError:
      return
    logging.debug('got player_name = ' + str(player_name))
    if player_name == 'tacshell':
      return '/say ' + target + ', quit being a NOOB!'
    else:
      return '/say You can\'t tell me what to do!'



class Server(threading.Thread):
  """Class representing a server's supervising thread."""

  # The name of the world the server will host.
  world = ""

  # The subproccess spawned by the thread.
  sub = None
  # The working directory of the spawned process.
  cwd = WORLDS_DIR
  # The status returned by the subprocess, None whilst it is still running.
  returncode = None
  # The jar file to pass to the JVM.
  mcserver = MCSERVER
  # The argument sequence to give to Popen.
  cmd = ['java']
  # Starting memory for the JVM.
  memstart = MEMSTART
  # Maximum memory for the JVM.
  memmax = MEMMAX

  # A Log object containing the subprocess's output.
  log = None
  # The socket used to communicate with the server.
  sock = None
  # The address the server will listen at.
  address = ""
  timeout = .05
  running = False
  returncode = None
  
  def __init__(self, world, line_parser=None, **kwargs):
    if type(world) != type(str()):
      raise TypeError('Expected a string argument.')
    self.world = world

    super(Server, self).__init__(name=self.world + '-Server')

    for kw in kwargs:
      if kw in dir(self):
        self.__setattr__(kw, kwargs[kw])

    self.cwd = os.path.join(WORLDS_DIR, world)
    if not os.path.isdir(self.cwd):
      raise Exception('Not a directory: ' + self.cwd)

    if not os.path.isfile(self.mcserver):
      raise Exception('Not a file: ' + self.mcserver)

    self.log = Log(name=self.world + '-Log', line_parser=line_parser)

    if type(self.cmd) == type(str()):
      self.cmd = [cmd]
    self.cmd += ['-Xms' + str(self.memstart), '-Xmx' + str(self.memmax),
                  '-jar', self.mcserver, 'nogui']

    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    self.sock.settimeout(self.timeout)
    self.address = os.path.join(self.cwd, self.world + '.sock') 
    return


  def start(self):
    def replace_handler():
      # Ignore SIGINT. The parent will handle this signal for the child.
      signal.signal(signal.SIGINT, signal.SIG_IGN)

    self.sub = subprocess.Popen(self.cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, cwd=self.cwd,
                                bufsize=0, universal_newlines=True,
                                preexec_fn=replace_handler)
    self.running = True
    self.log.start(read_stream=self.sub.stdout, ctrl_stream=self.sub.stdin)
    try:
      self.sock.bind(self.address)
    except OSError:
      logging.error('Address already in use: ' + self.address)
      self.stop(None, None)
      return
    self.sock.listen()
    super(Server, self).start()
    return


  def run(self):
    while self.sub.poll() == None:
      try:
        connection, client_addr = self.sock.accept()
      except socket.timeout:
        continue
      try:
        tokens = connection.recv(256).decode().split()
        verb = tokens[0].strip()
        if verb == 'shell':
          self.shell_server(connection)
      finally:
        connection.shutdown(socket.SHUT_RDWR)
        connection.close()

    self.stop(None, None)
    return


  def stop(self, signum, stack_frame):
    if self.running:
      self.running = False
      out = None
      try:
        out, err = self.sub.communicate(input='stop', timeout=30)
      except subprocess.TimeoutExpired:
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


  def wait(self):
    while self.sub.poll() == None:
      time.sleep(1)
    return


  def shell_client(self):
    return Shell(self.sock, self.address, self.world)


  def shell_server(self, connection):
    logging.debug('shell_server was called')
    connection.settimeout(self.timeout)

    output = ''.join(self.log.list_all_lines())
    connection.sendall(bytes(output, 'utf-8'))
    error = False
    while self.returncode == None:
      try:
        output = ''.join(self.log.list_newlines())
        connection.sendall(bytes(output, 'utf-8'))
        try:
          msg = connection.recv(4096)
          if len(msg) > 0:
            self.sub.stdin.write(msg.decode())
        except socket.timeout:
          continue
        except OSError:
          # connection is closed
          error = True
          break
      except BrokenPipeError:
        # connection is closed
        error = True
        break

    if not error:
      try:
        connection.sendall(bytes('The server has shut down.', 'utf-8'))
      except OSError or BrokenPipeError:
        pass
    logging.debug('shell_server is returning')
    return



class History():
  lines = []
  lines_len = 2048
  write_pos = 0
  read_pos = 0


  def __init__(self, length=None):
    if length != None:
      self.lines_len = length
    self.lines = ['']
    self.lines *= self.lines_len
    return


  def write(self, line):
    self.lines[self.write_pos] = line
    self.read_pos = self.write_pos
    self.write_pos = (self.write_pos + 1) % self.lines_len
    return


  def read_forward(self):
    if (self.write_pos - self.read_pos) % self.lines_len > 1:
      self.read_pos = (self.read_pos + 1) % self.lines_len
      line = self.lines[(self.read_pos + 1) % self.lines_len]
    else:
      line = ''
    return line


  def read_backwards(self):
    line = self.lines[self.read_pos]
    self.read_pos = (self.read_pos - 1) % self.lines_len
    return line



class Shell(Log):
  """Class representing a shell."""
  # The socket used to communicate with the server.
  sock = None
  address = ''
  timeout = 0.1

  # The number of lines the terminal has.
  max_y = 40
  # The number of columns the terminal has.
  max_x = 80
  # Note that all y < max_y and x < max_x for all (y,x) coordinates. 

  cursor_pos = 0
  buff = ''
  history = []
  stdscr = None
  prompt = '[{}]$'
  world = ''

  # Width of the pad used to hold user input.
  input_pad_len = 512
  display_width = 0
  # The left-most x-coordinate in the input pad which will be displayed.
  start_x = 0

  # History of lines sent to the server.
  history = None
  stdscr = None
  logwin = None
  promptwin = None
  editwin = None

  def __init__(self, sock, address, world, **kwargs):
    self.sock = sock
    self.address = address
    self.world = world

    self.sock.settimeout(self.timeout)
    super(Shell, self).__init__(read_stream=sock.makefile(buffering=1),
                                write_stream=None,
                                name=self.world + "-Shell-Log")
    for kw in kwargs:
      if kw in dir(self):
        self.__setattr__(kw, kwargs[kw])

    if len(self.world) > 0:
      self.prompt = self.prompt.format(self.world)
    else:
      self.prompt = '$'

    self.history = History()
    return


  def write(self, line):
    super(Shell, self).write(line)
    self.most_recent_read()
    self.draw_screen()
    return


  def update_size(self):
    if self.stdscr == None:
      return
    self.max_y, self.max_x = self.stdscr.getmaxyx()
    self.display_width = self.max_x-1 - len(self.prompt)-1 
    if curses.is_term_resized(self.max_y, self.max_x):
      curses.resizeterm(self.max_y, self.max_x)
      if self.logwin != None:
        self.logwin.resize(self.max_y-1, self.max_x)
      if self.promptwin != None:
        if self.max_x <= len(self.prompt):
          self.promptwin.erase()
          self.promptwin.resize(1, 1)
          self.promptwin.addstr(0,0, '$')
          self.promptwin.refresh()
        else:
          self.promptwin.erase()
          self.promptwin.resize(1, len(self.prompt)+1)
          self.promptwin.addstr(0,0, self.prompt)
          self.promptwin.refresh()
    return


  def split_string(self, string, n):
    """Split a string into blocks each of length n."""
    if len(string) == 0:
      return ['']
    blocks = []
    while len(string) > 0:
      blocks.append(string[:n])
      string = string[n:]
    return blocks


  def draw_log(self):
    """Draw the log on screen with the line pointed to by read_pos at
       the bottom. This is accomplished by filling the screen from the bottom
       to the top."""
    if self.logwin == None:
      return
    self.logwin.clear()
    max_y, max_x = self.logwin.getmaxyx()
    lines = self.list_prev_lines(max_y)
    k = 0
    n = max_y - 1
    while n >= 0:
      if k < len(lines):
        line = lines[k]
        k += 1
      else:
        break
      if len(line) == 0:
        line = '~'
      line = line.rstrip('\n\r')
      blocks = self.split_string(line, max_x-1)
      blocks.reverse()
      for block in blocks:
        self.logwin.addstr(n, 0, block)
        n -= 1
        if n < 0:
          break
    self.logwin.noutrefresh()
    return


  def draw_screen(self):
    if self.stdscr != None:
      self.stdscr.noutrefresh()
    self.draw_log()
    if self.promptwin != None:
      self.promptwin.clear()
      self.promptwin.addstr(0,0, self.prompt)
      self.promptwin.noutrefresh()
    if self.editwin != None:
      self.editwin.clear()
      self.editwin.addstr(0,0, self.buff)
      self.editwin.noutrefresh(0,self.start_x, self.max_y-1,len(self.prompt)+1,
                                               self.max_y-1,self.max_x-1)
    curses.setsyx(self.max_y-1, len(self.prompt) + 1 
                                + self.cursor_pos - self.start_x)
    curses.doupdate()
    return


  def check_startx(self):
    if self.cursor_pos < self.start_x:
      self.start_x = self.cursor_pos
    elif self.cursor_pos - self.start_x > self.display_width - 1:
      self.start_x = self.cursor_pos - self.display_width
    return


  def check_cursor(self):
    if self.cursor_pos < 0:
      self.cursor_pos = 0
    elif self.cursor_pos > len(self.buff):
      self.cursor_pos = len(self.buff)
    self.check_startx()
    return


  def seek_cursor(self, n):
    self.cursor_pos += n
    self.check_cursor()
    return


  def set_cursor(self, n):
    self.cursor_pos = n
    self.check_cursor()
    return


  def start(self):
    try:
      self.sock.connect(self.address)
    except FileNotFoundError:
      # The socket for the server does not exist.
      print('Could not connect to:', self.address)
      return

    self.stdscr = curses.initscr()
    self.stdscr.clear()
    curses.cbreak()
    curses.noecho()
    self.stdscr.keypad(True)

    try:
      self.update_size()
      self.logwin = curses.newwin(self.max_y-1,self.max_x, 0,0)
      self.promptwin = curses.newwin(1, len(self.prompt)+1, self.max_y-1, 0)
      self.promptwin.addstr(0,0, self.prompt)
      self.editwin = curses.newpad(1, self.input_pad_len)
      self.draw_screen()
      super(Shell, self).start()
      self.sock.sendall(bytes('shell', 'utf-8'))
      while True:
        c = self.stdscr.getch()
        if c == ascii.EOT:
          break
        elif c == curses.KEY_RESIZE:
          self.update_size()
        elif c == curses.KEY_UP:
          self.buff = self.history.read_backwards()
          self.set_cursor(len(self.buff))
        elif c == curses.KEY_DOWN:
          self.buff = self.history.read_forward()
          self.set_cursor(len(self.buff))
        elif c == curses.KEY_PPAGE:
          self.seek_read(-int((self.max_y - 1)/2))
        elif c == curses.KEY_NPAGE:
          self.seek_read(int((self.max_y - 1)/2))
        elif c == curses.KEY_LEFT:
          self.seek_cursor(-1)
        elif c == curses.KEY_RIGHT:
          self.seek_cursor(1)
        elif c == curses.KEY_END:
          self.set_cursor(len(self.buff))
        elif c == curses.KEY_HOME:
          self.set_cursor(0)
        elif 32 <= c and c <= 126:
          if len(self.buff) < self.input_pad_len - 1:
            self.buff = self.buff[:self.cursor_pos] + chr(c)\
                      + self.buff[self.cursor_pos:]
            self.seek_cursor(1)
          else:
            curses.beep()
            curses.flash()
        elif c == ascii.BS or c == ascii.DEL:
          self.buff = self.buff[:self.cursor_pos-1]\
                    + self.buff[self.cursor_pos:]
          self.seek_cursor(-1)
        elif c == ascii.NL or c == ascii.LF:
          self.history.write(self.buff)
          if self.running:
            try:
              self.sock.sendall(bytes(self.buff + '\n', 'utf-8'))
            except BrokenPipeError:
              self.stop()
              self.sock.close()
          self.buff = ''
          self.set_cursor(0)
        else:
          curses.beep()
          curses.flash()
        self.draw_screen()
    finally:
      self.stdscr.keypad(False)
      curses.echo()
      curses.nocbreak()
      curses.endwin()
      self.stop()
      self.sock.close()
    return



if __name__ == '__main__':
  import signal

  usage = 'Usage: '+ sys.argv[0] +' <start|shell> [world]'

  if len(sys.argv) < 2:
    print(usage)
    sys.exit(0)

  if sys.argv[1] == 'start':
    if len(sys.argv) < 3:
      print(usage)
      sys.exit(1)
    server = Server(sys.argv[2])
    signal.signal(signal.SIGTERM , server.stop)
    signal.signal(signal.SIGINT, server.stop)
    server.start()
    server.wait()
    sys.exit(server.returncode)
  elif sys.argv[1] == 'shell':
    server = Server(sys.argv[2])
    shell = server.shell_client()
    try:
      shell.start()
    except KeyboardInterrupt:
      shell.stop()
    sys.exit(0)
  else:
    print(usage)
    sys.exit(1)

  sys.exit(0)
