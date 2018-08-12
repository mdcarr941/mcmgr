#!/usr/bin/python3

import sys
import os
import socket
import random
import logging
import signal
import json
import io
import subprocess

if __name__ != '__main__':
  from .bearing import bearing
  from . import lineharness, config, LOGGER
else:
  from bearing import bearing
  from __init__ import LOGGER
  import lineharness, config



class MCLineParser(lineharness.LineParser):
  public_methods = ['help', 'save_coords', 'list_coords', 'del_coords',\
                    'display_coords', 'bearing', 'whoami', 'randint',\
                    'tell_time']


  def __init__(self, cwd=None):
    random.seed()

    self.places = dict()
    if cwd != None:
      self.places_file = os.path.join(cwd, 'places.json')
      try:
        with open(self.places_file, 'r') as fp:
          self.places = json.loads(fp.read())
      except FileNotFoundError as e:
        LOGGER.info('could not find places.json in cwd: ' + cwd)
        LOGGER.debug(e, exc_info=1)
      except json.decoder.JSONDecodeError as e:
        LOGGER.error('problem decoding: ' + cwd + '/places.json')
        LOGGER.debug(e, exc_info=1)
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
      LOGGER.debug('have tokens: ' + str(tokens))
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

    LOGGER.debug('tokens to be passed on: ' + str(tokens[5:]))
    if cmd in self.public_methods:
      method = self.__getattribute__(cmd)
      try:
        LOGGER.debug('calling: ' + cmd)
        return method(*tokens[5:], **meta).rstrip() + '\n'
      except lineharness.StopLogException as e:
        LOGGER.debug('StopLog exception raised.')
        raise e
      except Exception as e:
        LOGGER.error('Uncaught exception in called method.')
        LOGGER.debug(e, exc_info=1)
        return None


  def say(self, lines):
    cmd = '/say '
    if type(lines) == type(list()):
      cmd += '\n/say '.join(lines)
    else:
      cmd += str(lines)
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
    method_names = ['!' + x for x in self.public_methods]
    return self.say(', '.join(method_names))


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
      LOGGER.error('Error saving file: ' + self.places_file)
      LOGGER.debug(e, exc_info=1)
    return


  def get_player_name(self, **kwargs):
    if kwargs['server_flag']:
      return '__global__'
    else:
      return kwargs['player_name']


  def save_coords(self, *args, **kwargs):
    """Save coordinates <x> and <z> as <name>. \
Usage: !save_coords <name> <x> <z>"""

    player_name = self.get_player_name(**kwargs)
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


  def display_coords(self, *args, **kwargs):
    """Display a list of coordinates. \
Usage: !display_coords <name1> <name2> ..."""
    player_name = self.get_player_name(**kwargs)
    try:
      player_places = self.places[player_name]
    except KeyError:
      player_places = self.places['__global__']

    lines = []
    while True:
      try:
        coords = player_places[args[0]]
      except KeyError:
        try:
          coords = self.places['__global__'][args[0]]
        except KeyError:
          args = args[1:]
          continue
      except IndexError:
        break
      lines.append('%s = (%d, %d)' % (args[0], coords[0], coords[1]))
      args = args[1:]

    if len(lines) > 0:
      return self.say(lines)
    else:
      return self.say('unknown coordinates')


  def list_coords(self, *args, **kwargs):
    """List all coordinates usable by a player. Usage: !list_coords"""

    def make_list(places):
      lines = []
      for key, val in places.items():
        lines.append('%s = (%d, %d)' % (key, val[0], val[1]))
      return lines
      
    lines = make_list(self.places['__global__'])
    try:
      lines += make_list(self.places[kwargs['player_name']])
    except KeyError:
      pass
    if len(lines) > 0:
      return self.say(lines)
    else:
      return self.say('no saved coordinates')


  def del_coords(self, *args, **kwargs):
    """Delete a list of coordinates. Usage: !del_coords <name1> <name2> ..."""
    if kwargs['server_flag']:
      player_name = '__global__'
    else:
      player_name = kwargs['player_name']

    player_places = self.places[player_name]
    lines = []
    while True:
      try:
        del player_places[args[0]]
        lines.append(args[0] + ' deleted successfully.')
      except KeyError:
        lines.append('coordinates are unknown or global: ' + args[0])
      except IndexError:
        break
      args = args[1:]
    self.save_places()
    return self.say(lines)


  def bearing(self, *args, **kwargs):
    """Get the direction needed to travel between two points. Points \
can be referred to by name or by their X and Z coordinates. Usage: \
!bearing <x1 z1|name1> <x2 z2|name2>"""
    try:
      bearing((0,0), (0,0))
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
      return self.say(str(round(bearing(A, B), 2)))
      

  def randint(self, *args, **kwargs):
    """Generate a random integer N such that 1 <= N <= b. Usage: !randint <b>"""
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
  mcserver = config.MCSERVER
  # The argument sequence to give to Popen.
  cmd = ['java']
  # Starting memory for the JVM.
  memstart = config.MEMSTART
  # Maximum memory for the JVM.
  memmax = config.MEMMAX


  def __init__(self, world, cwd=None, address=None, backup_dir=None,
               line_parser=None, world_config_file='mcmgr.json', **kwargs):
    if type(world) != type(str()):
      raise TypeError('Expected a string argument.')
    self.world = world

    if cwd == None:
      self.cwd = os.path.join(config.WORLDS_DIR, world)
    else:
      self.cwd = cwd

    if not os.path.isdir(self.cwd):
      raise Exception('Not a directory: ' + self.cwd)

    if line_parser == None:
      line_parser = MCLineParser(cwd=self.cwd)

    super(MCServer, self).__init__(name=self.world, line_parser=line_parser,
                                   **kwargs)

    # Load the per-world configuration, if it is present.
    world_config_path = os.path.join(self.cwd, world_config_file)
    if os.path.isfile(world_config_path):
      with open(world_config_path) as fp:
        world_config = json.loads(fp.read())
      if 'mcserver' in world_config:
        self.mcserver = os.path.expanduser(world_config['mcserver'])
      if 'cmd' in world_config:
        self.cmd = world_config['cmd']
      if 'memstart' in world_config:
        self.memstart = world_config['memstart']
      if 'memmax' in world_config:
        self.memmax = world_config['memmax']

    if address == None:
      self.address = os.path.join(self.cwd, self.world + '.sock') 
    else:
      self.address = address

    if backup_dir == None:
      self.backup_dir = os.path.join(config.BACKUPS_DIR, world)
    else:
      self.backup_dir = backup_dir

    parent, _ = os.path.split(self.backup_dir)
    if not os.path.isdir(parent):
      raise Exception('Invalid backup directory, parent does not exist: '
                      + self.backup_dir)

    if not os.path.isabs(self.mcserver):
      self.mcserver = os.path.join(config.MCSERVER_DIR, self.mcserver)
    if not os.path.isfile(self.mcserver):
      raise Exception('mcserver is not a file: ' + self.mcserver)

    if type(self.cmd) == type(str()):
      self.cmd = [self.cmd]
    self.cmd += ['-Xms' + str(self.memstart), '-Xmx' + str(self.memmax),
                  '-jar', self.mcserver, 'nogui']

    self.server_methods += ['backup_server']
    return


  def stop_sub(self):
    return self.sub.communicate(input='stop', timeout=self.sub_timeout)


  def backup_client(self):
    try:
      self.sock.connect(self.address)
      self.sock.sendall(bytes('backup', 'utf-8'))
      self.sock.setblocking(True)
      # This will block until the server has finished saving the world.
      self.sock.recv(1)
      self.sock.close()
    except FileNotFoundError:
      # The server isn't running, just do the backup.
      pass

    returncode = -1
    try:
      backup_cmd = ['rdiff-backup', '-b', self.cwd, self.backup_dir]
      print('backing up "%s" to "%s"' % (self.cwd, self.backup_dir))
      rdiff = subprocess.Popen(backup_cmd, stdout=subprocess.PIPE)
      out, err = rdiff.communicate()
      if type(out) == type(bytes()):
        print(out.decode())
      if type(err) == type(bytes()):
        print(err.decode())
      returncode = rdiff.returncode
    except Exception as e:
      LOGGER.error('an exception occured in backup_client')
      LOGGER.debug(e, exc_info=1)
    return returncode


  def backup_server(self, server, connection, *args):
    LOGGER.debug('backup_server called')
    buf = io.StringIO()
    server.log.write_streams.append(buf)
    try:
      backup_log = lineharness.Log(read_stream=buf,
                                   line_parser=BackupLineParser())
      backup_log.start()
      server.sub.stdin.write('save-all\n')
      backup_log.join()
      # This unblocks the client process.
      connection.sendall(b'\x01')
    except Exception as e:
      LOGGER.error('an exception occured in backup_server')
      LOGGER.debug(e, exc_info=1)
    finally:
      server.log.write_streams.remove(buf)
      buf.close()
      connection.close()
      LOGGER.debug('backup_server returning')
      return



if __name__ == '__main__':
  usage = 'Usage: '+ sys.argv[0] +' <start|shell|backup> [world]'

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
      for world in os.listdir(path=config.WORLDS_DIR):
        path = os.path.join(config.WORLDS_DIR, world)
        if os.path.isdir(path):
          server = MCServer(world)
          if server.backup_client() != 0:
            returncode = -1
      sys.exit(returncode)
  else:
    print(usage)
    sys.exit(1)

  sys.exit(0)
