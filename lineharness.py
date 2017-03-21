import sys
import os
import threading
import select
import signal
import socket
import subprocess
import logging
import curses
from curses import ascii

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
  cmd = ['true']
  cwd = os.getcwd()


  def __init__(self, name, **kwargs):
    super(Server, self).__init__(name=name)

    for kw in kwargs:
      if kw in dir(self):
        self.__setattr__(kw, kwargs[kw])

    os.chdir(self.cwd)
    self.log = Log(name=name + '-Log', line_parser=self.line_parser)

    if 'address' not in dir(self):
      self.address = self.name + '.sock'
    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    self.timeout = .05
    self.sock.settimeout(self.timeout)
    self.running = False
    self.returncode = None
    self.sub = None
    self.server_methods = ['shell_server']
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

    # Start the thread.
    super(Server, self).start()
    return


  def respond(self, connection):
    tokens = connection.recv(4096).decode().split()
    if len(tokens) == 0:
      return
    method_name = tokens[0].strip() + '_server'
    tokens = tokens[1:]
    if method_name in self.server_methods:
      method = self.__getattribute__(method_name)
      worker = threading.Thread(target=method,
                                args=(self, connection, *tokens))
      # The called method is responsible for closing the connection.
      worker.start()
    else:
      connection.close()
    return


  def run(self):
    while self.sub.poll() == None:
      try:
        connection, _ = self.sock.accept()
      except socket.timeout:
        continue
      self.respond(connection)

    self.stop()
    return


  def stop_sub(self):
    self.sub.terminate()
    return self.sub.communicate(timeout=self.sub_timeout)


  def stop(self, *args):
    if self.running:
      self.running = False
      out = None
      try:
        out, err  = self.stop_sub()
        if err != None and len(err) > 0:
          print(err, file=sys.stderr)
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


  def shell_client(self):
    return Shell(self.sock, self.address, self.name)


  def shell_server(self, server, connection, *args):
    logger.debug('shell_server was called')
    connection.settimeout(server.timeout)

    try:
      shell_stream = connection.makefile(mode='w', buffering=1)
      output = ''.join(server.log.list_all_lines())
      shell_stream.write(output)
      shell_stream.flush()
      server.log.write_streams.append(shell_stream)
      error = False
      while server.running and server.sub.poll() == None:
        try:
          data = connection.recv(4096)
          if len(data) == 0:
            error = True
            break
          server.sub.stdin.write(data.decode())
        except socket.timeout:
          continue
        except OSError:
          error = True
          break

      if not error:
        shell_stream.write('The server has shut down.')
      shell_stream.close()
    except Exception as e:
      logger.error('an exception occured in shell_server')
      logger.debug(e)
    finally:
      try:
        server.log.write_streams.remove(shell_stream)
      except ValueError:
        pass
      connection.close()
      logger.debug('shell_server is returning')
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


  def __init__(self, sock, address, name, **kwargs):
    sock.setblocking(True)
    super(Shell, self).__init__(read_stream=sock.makefile(buffering=1),
                                write_streams=[],
                                name=name + "-Shell-Log")
    self.sock = sock
    self.address = address
    self.name = name

    self.prompt = '[{}]$'
    if len(self.name) > 0:
      self.prompt = self.prompt.format(self.name)
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


  def write(self, lines):
    super(Shell, self).write(lines)
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


  def start_shell(self):
    self.stdscr = curses.initscr()
    self.stdscr.clear()
    curses.cbreak()
    curses.noecho()
    self.stdscr.keypad(True)
    return


  def stop_shell(self):
    self.stdscr.keypad(False)
    curses.echo()
    curses.nocbreak()
    curses.endwin()
    return


  def start(self):
    try:
      self.sock.connect(self.address)
    except FileNotFoundError:
      # The socket for the server does not exist.
      print('Could not connect to:', self.address)
      print('Is the server running?')
      return

    self.start_shell()
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
        elif c == curses.KEY_F1:
          self.stop_shell()
          import pdb
          pdb.set_trace()
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
        elif c == ascii.BS or c == ascii.DEL or c == curses.KEY_BACKSPACE:
          self.buff = self.buff[:self.cursor_pos-1]\
                    + self.buff[self.cursor_pos:]
          self.seek_cursor(-1)
        elif c == ascii.NL or c == ascii.LF or c == curses.KEY_ENTER:
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
      self.stop_shell()
      self.stop()
      self.sock.close()
    return
