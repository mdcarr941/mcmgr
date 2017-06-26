# Installation
This program uses the lineharness module which needs to be initialized before
you can use it. Run the following to accomplish this:
  git submodule init
  git submodule update
(if you used the recursive flag when cloning mcmgr then you don't need to do
this)

Provided your python3 environment is setup, you can invoke mcmgr by running:
  ./main.py start <world_name>
where <world_name> is a subdirectory of ~/worlds
containing the world you want to start.
