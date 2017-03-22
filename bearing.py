#!/usr/bin/python3

from math import pi, atan

def bearing(A,B):
  """
  The bearing needed to travel from A to B in minecraft. Arguments should
  be tuples of (X,Z) coordinates. Recall that the X coordinate in minecraft
  runs from west to east and the Z coordinate runs from north to south.
  """
  dy = B[0]-A[0]
  dx = B[1]-A[1]

  if dx == 0:
    if dy >= 0:
      th = 90
    else:
      th = -90
    return -th

  th = 180*atan(dy/dx)/pi
  if dx < 0:
    if dy >= 0:
      th = 180+th
    else:
      th = th-180
  return -th

if __name__ == '__main__':
  from sys import argv, exit

  def get_args(argv, k):
    try:
      P = places[argv[k]]
      k += 1
    except IndexError:
      print(usage)
      exit(1)
    except KeyError:
      try:
        P = (int(argv[k]), int(argv[k+1]))
        k += 2
      except ValueError:
        print(usage)
        exit(1)
    return P, k

  usage = 'Usage: ' + argv[0] + ' <place name|X1 Z1> <place name|X2 Z2>'
  k = 1
  A, k = get_args(argv, k)
  B, k = get_args(argv, k)
  print(bearing(A,B))
