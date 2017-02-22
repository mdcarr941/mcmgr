#!/bin/python3

import curses

def main(stdscr):
  stdscr.clear()
  curses.noecho()
  stdscr.keypad(True)

  for y in range(0, curses.LINES-1):
    for x in range(0, curses.COLS-1):
      stdscr.addch(y,x, ord('a') + (x*x+y*y) % 26)
  stdscr.refresh()

  stdscr.getch()
  return

curses.wrapper(main)
