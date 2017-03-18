#!/usr/bin/python3

import sys
import os
import socket
import random
import logging
import curses
from curses import ascii
import signal
import json
import io
import subprocess
import threading

import lineharness
import bearing

WORLDS_DIR = os.path.join(os.environ['HOME'], 'worlds')
BACKUPS_DIR = os.path.join(os.environ['HOME'], 'backups')
MCSERVER = os.path.join(os.environ['HOME'], 'mcservers', 'minecraft_server.jar')
MEMSTART = '256M'
MEMMAX = '1G'
LOGFILE = os.path.join(os.environ['HOME'], 'mcmgr.log')

logger = logging.getLogger('mcmgr')

def configure_logging(level):
  logger.setLevel(level)
  f = logging.Formatter(fmt='%(asctime)s:%(levelname)s:%(message)s')
  h = logging.StreamHandler(stream=sys.stderr)
  h.setLevel(logging.WARNING)
  h.setFormatter(f)
  logger.addHandler(h)
  h = logging.FileHandler(LOGFILE)
  h.setLevel(logging.DEBUG)
  h.setFormatter(f)
  logger.addHandler(h)

configure_logging(logging.INFO)



class MCLineParser(lineharness.LineParser):
  public_methods = ['help', 'save_coords', 'list_coords', 'del_coords',\
                    'bearing', 'whoami', 'randint', 'tell_time']


  def __init__(self, cwd=None):
    random.seed()

    self.places = dict()
    if cwd != None:
      self.places_file = os.path.join(cwd, 'places.json')
      try:
        with open(self.places_file, 'r') as fp:
          self.places = json.loads(fp.read())
      except FileNotFoundError as e:
        logger.error('could not find places.json in cwd: ' + cwd)
        logger.debug(str(e))
      except json.decoder.JSONDecodeError as e:
        logger.error('problem decoding: ' + cwd + '/places.json')
        logger.debug(str(e))
    if '__global__' not in self.places:
      self.places['__global__'] = dict()
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


  def parse(self, line):
    """Tokenize a line, extract metadata, and pass on the remainding tokens \
to another method."""

    tokens = self.tokenize(line)
    if len(tokens) > 0:
      logger.debug('have tokens: ' + str(tokens))
    if len(tokens) < 5:
      return

    cmd = tokens[4]
    if cmd[0] != '!':
      return
    else:
      cmd = cmd[1:]

    meta = dict()
    meta['time'] = tokens[0]
    meta['tag'] = tokens[1]

    meta['server_flag'] = False
    meta['player_name'] = self.delim_extract(tokens[3], delims='<>')
    if meta['player_name'] == None and tokens[3] == 'Server':
      meta['player_name'] = 'Server'
      meta['server_flag'] = True

    logger.debug('tokens to be passed on: ' + str(tokens[5:]))
    if cmd in self.public_methods:
      method = self.__getattribute__(cmd)
      try:
        logger.debug('calling: ' + cmd)
        return method(*tokens[5:], **meta).rstrip() + '\n'
      except lineharness.StopLogException as e:
        raise e
      except Exception as e:
        logger.error('Uncaught exception in called method.')
        logger.debug(str(e))
        return None


  def say(self, *args, **kwargs):
    cmd = '/say '
    try:
      cmd += str(args[0])
    except IndexError:
      pass
    return cmd


  def invalid_args(self, *args, **kwargs):
    msg = 'Invalid arguments. '
    try:
      msg += str(args[0])
    except IndexError:
      pass
    return self.say(msg)


  def help(self, *args, **kwargs):
    """List available commands and provide information about them."""
    try:
      method = self.__getattribute__(args[0])
      if args[0] in self.public_methods:
        return self.say(method.__doc__)
    except (IndexError, AttributeError):
      pass
    return self.say(', '.join(self.public_methods))


  def tell_time(self, *args, **kwargs):
    """Return the current server time."""
    return self.say(kwargs['time'])


  def whoami(self, *args, **kwargs):
    """Return the user name seen by the server."""
    return self.say(kwargs['player_name'])


  def save_places(self):
    """Save the places dictionary to a file."""
    try:
      with open(self.places_file, 'w') as fp:
        fp.write(json.dumps(self.places))
    except NameError:
      # self.places_file was not defined in init, not a problem
      pass
    except FileNotFoundError as e:
      logger.error('Error saving file: ' + self.places_file)
      logger.debug(e)
    return


  def save_coords(self, *args, **kwargs):
    """Save coordinates <x> and <z> as <name>. \
Usage: save_coords <name> <x> <z>"""
    if kwargs['server_flag']:
      player_name = '__global__'
    else:
      player_name = kwargs['player_name']

    try:
      player_places = self.places[player_name]
    except KeyError:
      player_places = dict()
      self.places[player_name] = player_places

    try:
      player_places[args[0]] = [int(args[1]), int(args[2])]
    except (IndexError, ValueError):
      return self.invalid_args(self.save_coords.__doc__)

    self.save_places()
    return self.say('(%s, %s) saved as %s' % (args[1], args[2], args[0]))


  def list_coords(self, *args, **kwargs):
    """List all coordinates usable by a player. Usage: list_coords"""

    def make_list(places):
      str_list = []
      for key, val in places.items():
        str_list.append('%s = (%d, %d)' % (key, val[0], val[1]))
      return str_list
      
    str_list = make_list(self.places['__global__'])
    try:
      str_list += make_list(self.places[kwargs['player_name']])
    except KeyError:
      pass
    if len(str_list) > 0:
      return self.say('\n/say '.join(str_list))
    else:
      return self.say('no saved coordinates')


  def del_coords(self, *args, **kwargs):
    """Delete the coordinates known by <name>. Usage: del_coords <name>"""
    if kwargs['server_flag']:
      player_name = '__global__'
    else:
      player_name = kwargs['player_name']
    try:
      del self.places[player_name][args[0]]
    except (KeyError, IndexError):
      return self.say('No coordinates with that name.')
    self.save_places()
    return self.say('%s deleted successfully.' % args[0])


  def bearing(self, *args, **kwargs):
    """Get the direction needed to travel between two points. Points \
can be referred to by name or by their X and Z coordinates. Usage: \
bearing <x1 z1|name1> <x2 z2|name2>"""
    try:
      bearing.bearing((0,0), (0,0))
    except NameError:
      return

    def get_args(args):
      P = None
      try:
        P = self.places['__global__'][args[0]]
        args = args[1:]
      except IndexError:
        return None, args
      except KeyError:
        try:
          P = self.places[kwargs['player_name']][args[0]]
          args = args[1:]
        except KeyError:
          try:
            P = (int(args[0]), int(args[1]))
            args = args[2:]
          except (ValueError, IndexError):
            pass
      return P, args

    A, args = get_args(args)
    B, args = get_args(args)
    if A == None or B == None:
      return self.invalid_args(self.bearing.__doc__)
    else:
      return self.say(str(round(bearing.bearing(A, B), 2)))
      

  def randint(self, *args, **kwargs):
    """Generate a random integer N such that 1 <= N <= b. Usage: randint <b>"""
    try:
      cmd = str(random.randint(1, int(args[0])))
      return self.say(cmd)
    except (ValueError, IndexError):
      return self.invalid_args(self.randint.__doc__)



class BackupLineParser(MCLineParser):
  def parse(self, line):
    tokens = self.tokenize(line)
    message = ' '.join(tokens[3:])
    if message == 'Saved the world':
      raise StopLogException



class MCServer(lineharness.Server):
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


  def __init__(self, world, cwd=None, address=None, backup_dir=None,
               line_parser=None, **kwargs):
    if type(world) != type(str()):
      raise TypeError('Expected a string argument.')
    self.world = world

    if cwd == None:
      self.cwd = os.path.join(WORLDS_DIR, world)
    else:
      self.cwd = cwd

    if address == None:
      self.address = os.path.join(self.cwd, self.world + '.sock') 
    else:
      self.address = address

    if backup_dir == None:
      self.backup_dir = os.path.join(BACKUPS_DIR, world)
    else:
      self.backup_dir = backup_dir

    if line_parser == None:
      line_parser = MCLineParser(cwd=self.cwd)

    super(MCServer, self).__init__(name=self.world, line_parser=line_parser,
                                   **kwargs)

    if not os.path.isdir(self.cwd):
      raise Exception('Not a directory: ' + self.cwd)
    if not os.path.isdir(os.path.dirname(self.backup_dir)):
      raise Exception('Invalid backup directory: ' + self.backup_dir)
    if not os.path.isfile(self.mcserver):
      raise Exception('Not a file: ' + self.mcserver)

    if type(self.cmd) == type(str()):
      self.cmd = [self.cmd]
    self.cmd += ['-Xms' + str(self.memstart), '-Xmx' + str(self.memmax),
                  '-jar', self.mcserver, 'nogui']
    return


  def respond(self, connection):
    tokens = connection.recv(256).decode().split()
    if len(tokens) == 0:
      return
    verb = tokens[0].strip()
    if verb == 'shell':
      worker = threading.Thread(target=self.shell_server,
                                args=(self, connection), daemon=True)
      worker.start()
    elif verb == 'backup':
      worker = threading.Thread(target=self.backup_server,
                                args=(self, connection), daemon=True)
      worker.start()
    return


  def stop_sub(self):
    out, err = self.sub.communicate(input='stop', timeout=self.sub_timeout)
    return


  def shell_client(self):
    return Shell(self.sock, self.address, self.world)


  def shell_server(self, server, connection):
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
    except OSError as e:
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


  def backup_client(self):
    returncode = -1

    try:
      self.sock.connect(self.address)
      self.sock.sendall(bytes('backup', 'utf-8'))
      self.sock.setblocking(True)
      self.sock.recv(1)
      self.sock.close()
    except FileNotFoundError:
      # The server isn't running, just do the backup.
      pass

    try:
      cmd = ['rdiff-backup', self.cwd, self.backup_dir]
      print('backing up "%s" to "%s"' % (self.cwd, self.backup_dir))
      rdiff = subprocess.Popen(cmd, stdout=subprocess.PIPE)
      out, err = rdiff.communicate()
      if type(out) == type(bytes()):
        print(out.decode())
      if type(err) == type(bytes()):
        print(err.decode())
      returncode = rdiff.returncode
    except Exception as e:
      logger.error('an exception occured in backup_client')
      logger.debug(e)
    return returncode


  def backup_server(self, server, connection):
    logger.debug('backup_server called')
    buf = io.StringIO()
    server.log.write_streams.append(buf)
    try:
      backup_log = lineharness.Log(read_stream=buf,
                                   line_parser=BackupLineParser())
      backup_log.start()
      server.sub.stdin.write('save-all flush\n')
      backup_log.join()
      # This unblocks the client process.
      connection.sendall(b'\x01')
    except Exception as e:
      logger.error('an exception occured in backup_server')
      logger.debug(e)
    finally:
      server.log.write_streams.remove(buf)
      buf.close()
      connection.close()
      logger.debug('backup_server returning')
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



class Shell(lineharness.Log):
  """Class representing a shell."""


  def __init__(self, sock, address, world, **kwargs):
    self.sock = sock
    self.address = address
    self.world = world

    self.sock.setblocking(True)
    super(Shell, self).__init__(read_stream=sock.makefile(buffering=1),
                                write_streams=[],
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
    server = MCServer(sys.argv[2])
    signal.signal(signal.SIGTERM , server.stop)
    signal.signal(signal.SIGINT, server.stop)
    server.start()
    server.join()
    sys.exit(server.returncode)
  elif sys.argv[1] == 'shell':
    server = MCServer(sys.argv[2])
    shell = server.shell_client()
    try:
      shell.start()
    except KeyboardInterrupt:
      shell.stop()
    sys.exit(0)
  elif sys.argv[1] == 'backup':
    if len(sys.argv) >= 3:
      server = MCServer(sys.argv[2])
      sys.exit(server.backup_client())
    else:
      returncode = 0
      for world in os.listdir(path=WORLDS_DIR):
        path = os.path.join(WORLDS_DIR, world)
        if os.path.isdir(path):
          server = MCServer(world)
          if server.backup_client() != 0:
            returncode = -1
      sys.exit(returncode)
  else:
    print(usage)
    sys.exit(1)

  sys.exit(0)
