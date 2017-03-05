#!/usr/bin/python3

import sys
import os
import subprocess
import socket
import threading
import select
import random
import logging
import curses
from curses import ascii

try:
  import bearing
except ImportError:
  pass

WORLDS_DIR = os.path.join(os.environ['HOME'], 'worlds')
MCSERVER = os.path.join(os.environ['HOME'], 'mcservers', 'minecraft_server.jar')
MEMSTART = '256M'
MEMMAX = '1G'
LOGFILE = 'mcmgr.log'

logging.basicConfig(filename=LOGFILE, level=logging.INFO)



class StopLogException(Exception):
  """Exception thrown by a LineParser to signal a Log to stop."""
  pass



class LineParser():
  """Parse the lines written to a Log."""
  public_methods = ['bearing', 'admonish', 'randint', 'tell_time']


  def bearing(self, *args, **kwargs):
    """Get the direction needed to travel between two points."""
    try:
      bearing.bearing((0,0), (0,0))
    except NameError:
      return

    def get_args(args):
      if len(args) == 0:
        return None
      P = None
      try:
        P = bearing.places[args[0]]
        args = args[1:]
      except KeyError:
        try:
          P = (int(args[0]), int(args[1]))
          args = args[2:]
        except IndexError or ValueError:
          pass
      return P, args

    A, args = get_args(args)
    B, args = get_args(args)
    if A == None or B == None:
      return None
    else:
      return '/say ' + str(round(bearing.bearing(A, B), 2))
      

  def randint(self, *args, **kwargs):
    """Generate a random integer N such that 1 <= N <= b."""
    b = args[0] 
    cmd = '/say '
    try:
      b = int(b)
      cmd += str(random.randint(1, b))
    except ValueError:
      cmd += 'ValueError: expected an integer'
    return cmd


  def admonish(self, *args, **kwargs):
    target = args[0]
    try:
      player_name = kwargs['player_name']
    except KeyError:
      return
    logging.debug('got player_name = ' + str(player_name))
    if player_name == 'Server':
      return '/say ' + target + ', did you really think that would work?'
    else:
      return '/say You can\'t tell me what to do!'


  def tell_time(self, *args, **kwargs):
    return '/say ' + kwargs['time']


  def __init__(self):
    random.seed()
    return


  def tokenize(self, line, lws=' \t', delims='[]'):
    ld = delims[0]
    rd = delims[1]
    line = line.lstrip().rstrip()

    delim_flag = False
    tokens = []
    start = -1
    for n in range(len(line)):
      c = line[n]
      if delim_flag:
        if c != rd:
          continue
        elif n > start:
          tokens.append(line[start:n])
          delim_flag = False
          start = -1
          continue
      if start < 0 and c == ld:
        start = n + 1
        delim_flag = True
        continue
      if start < 0 and c not in lws:
        start = n
        continue
      if start >= 0 and c in lws:
        if n > start:
          tokens.append(line[start:n])
        start = -1
    if start >= 0:
      tokens.append(line[start:])
    return tokens


  def delim_extract(self, token, delims='[]'):
    left_delim = delims[0]
    right_delim = delims[1]

    lp = token.find(left_delim)
    if lp == -1:
      return None

    rp = token.find(right_delim, lp)
    if rp <= lp:
      rp = None
    return token[lp + 1:rp]


  def mutator(self, line):
    return line


  def parse(self, line):
    """Tokenize a line, extract metadata, and pass on the remainding tokens
       to another method."""

    tokens = self.tokenize(line)
    if len(tokens) > 0:
      logging.debug('have tokens: ' + str(tokens))
    if len(tokens) < 5:
      return

    meta = dict()
    meta['time'] = tokens[0]
    meta['tag'] = tokens[1]

    meta['server_flag'] = False
    meta['player_name'] = self.delim_extract(tokens[3], delims='<>')
    if meta['player_name'] == None and tokens[3] == 'Server':
      meta['player_name'] = 'Server'
      meta['server_flag'] = True

    token = tokens[4]
    logging.debug('tokens to be passed on: ' + str(tokens[5:]))
    if token in self.public_methods:
      method = self.__getattribute__(token)
      try:
        logging.debug('calling: ' + token)
        return method(*tokens[5:], **meta) + '\n'
      except StopLogException as e:
        raise e
      except Exception as e:
        logging.error('Uncaught exception in called method.')
        logging.debug(str(e))
        return None



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
  advance_flag = False
  write_pos = 0
  read_pos = 0


  def __init__(self, name=None, **kwargs):
    super(Log, self).__init__(target='daemon', name=name)

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


  def list_newlines(self):
    return [line for line in self]


  def write(self, line):
    if line == None:
      return

    line = self.line_parser.mutator(line)

    try:
      message = self.line_parser.parse(line)
    except StopLogException:
      self.stop()
      return

    self.log[self.write_pos] = line
    self.advance_write()

    if message != None and self.ctrl_stream != None\
                       and not self.ctrl_stream.closed:
      self.ctrl_stream.write(str(message))

    if self.write_stream != None and not self.write_stream.closed:
      self.write_stream.write(line)
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
  """Class representing a server's supervising thread."""
  # The name of the world the server will host.
  world = ""
  # The jar file to pass to the JVM.
  mcserver = MCSERVER
  # The argument sequence to give to Popen.
  cmd = ['java']
  # Starting memory for the JVM.
  memstart = MEMSTART
  # Maximum memory for the JVM.
  memmax = MEMMAX
  # Number of seconds to wait for subprocess to exit.
  sub_timeout = 30

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
      self.cmd = [self.cmd]
    self.cmd += ['-Xms' + str(self.memstart), '-Xmx' + str(self.memmax),
                  '-jar', self.mcserver, 'nogui']

    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    self.timeout = .05
    self.sock.settimeout(self.timeout)
    self.address = os.path.join(self.cwd, self.world + '.sock') 
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
        if len(tokens) == 0:
          continue
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
        out, err = self.sub.communicate(input='stop', timeout=self.sub_timeout)
      except subprocess.TimeoutExpired:
        logging.warning('Timeout for subprocess exit has expired, '
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


  def __init__(self, length=2048):
    self.lines_len = length
    self.lines = ['']
    self.lines *= self.lines_len
    self.write_pos = 0
    self.read_pos = 0
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


  def __init__(self, sock, address, world, **kwargs):
    self.sock = sock
    self.address = address
    self.world = world

    self.sock.settimeout(None)
    super(Shell, self).__init__(read_stream=sock.makefile(buffering=1),
                                write_stream=None,
                                name=self.world + "-Shell-Log")

    self.prompt = '[{}]$'
    if len(self.world) > 0:
      self.prompt = self.prompt.format(self.world)
    else:
      self.prompt = '$'

    # The number of lines the terminal has.
    self.max_y = 40
    # The number of columns the terminal has.
    self.max_x = 80
    # Note that all y < max_y and x < max_x for all (y,x) coordinates. 

    # Width of the pad used to hold user input.
    self.input_pad_len = 512
    # The width of the part of the pad that will be displayed.
    self.display_width = 0
    # The left-most x-coordinate in the input pad which will be displayed.
    self.start_x = 0
    self.cursor_pos = 0

    self.history = History()
    self.buff = ''
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
    server.join()
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
