import logging
import os

WORLDS_DIR = os.path.join(os.environ['HOME'], 'worlds')
BACKUPS_DIR = os.path.join(os.environ['HOME'], 'backups')
MCSERVER_DIR = os.path.join(os.environ['HOME'], 'mcservers')
MCSERVER = os.path.join(MCSERVER_DIR, 'minecraft_server.jar')
MEMSTART = '512M'
MEMMAX = '2G'
LOGFILE = os.path.join(os.environ['HOME'], 'mcmgr.log')
LOGLEVEL = logging.INFO
#LOGLEVEL = logging.DEBUG
