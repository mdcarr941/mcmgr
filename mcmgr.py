#!/usr/bin/python3
import sys
import os
import subprocess
import time
import socket
import threading
import shutil

WORLDS_DIR = os.path.join(os.environ['HOME'], 'worlds')
MCSERVER = os.path.join(os.environ['HOME'], 'mcservers', 'minecraft_server.jar')
MEMSTART = '256M'
MEMMAX = '1G'

class Log(threading.Thread):
  """A class containing the lines output by a subprocess."""
  log = []
  log_len = 4096
  write_pos = 0
  read_pos = 0
  running = False

  # The stream object that the log will read from.
  read_stream = sys.stdin
  # The stream object the log will write to.
  write_stream = sys.stdout


  # Should read_pos be advanced?
  advance_flag = False

  def __init__(self, max_lines=None, read_stream=None, write_stream=None,
               *args, **kwargs):
    super(Log, self).__init__(target='daemon', *args, **kwargs)
    if type(max_lines) == type(int()):
      self.log_len = max_lines

    if type(read_stream) == type(self.read_stream):
      self.read_stream = read_stream
    if type(write_stream) == type(self.write_stream):
      self.write_stream = write_stream

    self.log.append("")
    self.log *= self.log_len
    return


  def __str__(self):
    rv = ""
    for line in self.log:
      rv += line
    return rv


  def write(self, line):
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


  def start(self, read_stream=None, write_stream=None):
    if read_stream != None:
      self.read_stream = read_stream
    if write_stream != None:
      self.write_stream = write_stream
    self.running = True
    super(Log, self).start()
    return


  def run(self):
    while self.running:
      if self.read_stream.closed:
        break
      try:
        line = self.read_stream.readline()
        if len(line) > 0:
          self.write(line)
      except OSError or ValueError:
        break
    self.running = False
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


  def serialize(self):
    start = self.write_pos
    oldest = start 
    while self.log[oldest] == '':
      oldest = (oldest + 1) % self.log_len
      if oldest == start:
        break
    output = ''
    for k in range(self.log_len):
      output += self.log[k + oldest]
    self.read_pos = self.write_pos
    return output


  def get_newlines(self):
    output = ""
    for line in self:
      output += line
    return output



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
  connection = None
  timeout = .05
  
  def __init__(self, world, max_lines=None, mcserver=None, cmd=None,
               *args, **kwargs):
    if type(world) != type(str()):
      raise TypeError('Expected a string argument.')
    self.world = world

    super(Server, self).__init__(name=self.world + '-Server', **kwargs)
    self.log = Log(max_lines=max_lines, name=self.world + '-Log')

    self.cwd = os.path.join(WORLDS_DIR, world)
    if not os.path.isdir(self.cwd):
      raise Exception('Not a directory: ' + self.cwd)

    if type(mcserver) == type(str()):
      self.mcserver = mcserver
    if not os.path.isfile(self.mcserver):
      raise Exception('Not a file: ' + self.mcserver)

    if type(cmd) == type(list()):
      self.cmd = cmd
    else:
      if type(cmd) == type(str()):
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
    self.log.start(read_stream=self.sub.stdout)
    self.sock.bind(self.address)
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
        verb = tokens[0]
        if verb == 'shell':
          self.shell_server(connection)
      finally:
        connection.close()

    self.stop(None, None)
    return


  def stop(self, signum, stack_frame):
    if self.sub.poll() == None:
      try:
        out, err = self.sub.communicate(input='stop', timeout=60)
      except subprocess.TimeoutExpired:
        self.sub.kill()
        out, err = self.sub.communicate()
      self.log.write(out)
    time.sleep(1)
    self.log.stop()

    if self.connection != None:
      self.connection.close()
      self.connection = None

    try:
      os.unlink(self.address)
    except FileNotFoundError:
      pass

    self.returncode = self.sub.returncode
    return


  def wait(self):
    while self.sub.poll() == None:
      time.sleep(1)
    return


  def shell_client(self):
    return Shell(self.sock, self.address)


  def shell_server(self, connection):
    print('shell_server was called')
    timeout = connection.gettimeout()
    connection.settimeout(self.timeout)

    connection.sendall(bytes(self.log.serialize(), 'utf-8'))
    while True:
      try:
        output = self.log.get_newlines()
        if len(output) > 0:
          print('sending:', output)
        connection.sendall(bytes(output, 'utf-8'))
        try:
          msg = connection.recv(4096)
          if len(msg) > 0:
            self.sub.stdin.write(msg.decode())
        except socket.timeout:
          continue
        except OSError:
          # connection is closed
          break
      except BrokenPipeError:
        # connection is closed
        break

    connection.settimeout(timeout)
    print('shell_server is returning')
    return



class Shell(Log):
  """Class representing a shell."""
  # The socket used to communicate with the server.
  sock = None
  address = ''

  # Current line of input.
  line = ''

  # The backspace character.
  bs = b'\x08'

  # Standard output opened in binary write mode.
  out = None

  def __init__(self, sock, address, *args, **kwargs):
    self.sock = sock
    self.sock.settimeout(None)
    self.address = address
    super(Shell, self).__init__(read_stream=sock.makefile(), *args, **kwargs)
    return


  def start(self, *args, **kwargs):
    self.stdout = open('/dev/stdout', 'wb')
    self.sock.connect(self.address)
    self.sock.sendall(bytes('shell', 'utf-8'))
    super(Shell, self).start(*args, **kwargs)

    self.running = True
    while self.running:
      c = sys.stdin.read(1)
      if c == '':
        break
      elif c == '\n':
        self.sock.sendall(bytes(self.line, 'utf-8'))
        self.line = ''
      self.render()
      self.line += c
    self.sock.close()
    self.stop()
    self.stdout.close()
    return


  def render(self):
    shell_prompt = bytes('>> ', 'utf-8')
    esc = b'\x1b'
    reset = esc + bytes('[0;0H', 'utf-8')

    sz = shutil.get_terminal_size((80,20))
    blank = bytes(' ', 'utf-8') * sz.lines * sz.columns

    # Note that write_pos could change whilst rendering, so this is needed.
    latest = (self.write_pos - 1) % self.log_len
    line_num = (latest - sz.lines + 1) % self.log_len
    output = b''
    while line_num != latest:
      out_line = self.log[line_num][:sz.columns]
      if len(out_line) == sz.columns:
        out_line = out_line[:-1] + '\\'
      output += bytes(out_line, 'utf-8')
      line_num = (line_num + 1) % self.log_len
    self.stdout.write(blank + reset + output + shell_prompt 
                            + bytes(self.line, 'utf-8'))
    self.stdout.flush()
    return


  def write(self, line):
    self.log[self.write_pos] = line
    self.write_pos = (self.write_pos + 1) % self.log_len
    self.render()
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
