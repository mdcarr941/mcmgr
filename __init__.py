import logging
import sys

if __name__ != '__init__':
  from . import config
else:
  import config

def configure_logger(logger, level):
  logger.setLevel(level)
  f = logging.Formatter(fmt='%(asctime)s:%(levelname)s:%(message)s')
  h = logging.StreamHandler(stream=sys.stderr)
  h.setLevel(logging.WARNING)
  h.setFormatter(f)
  logger.addHandler(h)
  h = logging.FileHandler(config.LOGFILE)
  h.setLevel(logging.DEBUG)
  h.setFormatter(f)
  logger.addHandler(h)

LOGGER = logging.getLogger(__name__)
configure_logger(LOGGER, config.LOGLEVEL)
