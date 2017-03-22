import logging
import os

WORLDS_DIR = os.path.join(os.environ['HOME'], 'worlds')
BACKUPS_DIR = os.path.join(os.environ['HOME'], 'backups')
MCSERVER = os.path.join(os.environ['HOME'], 'mcservers',
                        'minecraft_server.jar')
MEMSTART = '256M'
MEMMAX = '1G'
LOGFILE = os.path.join(os.environ['HOME'], 'mcmgr.log')
LOGLEVEL = logging.INFO
