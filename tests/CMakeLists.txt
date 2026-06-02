#
# CMakeLists for tests/ – registers all test sub‑directories with Zephyr
# and allows `west twister -s tests` to discover them.
#
# Currently we only have the "xd58c" sub‑folder, but adding an
# explicit add_subdirectory makes it simple to include more later.
#
# NOTE
# -----
# In a pure Zephyr project you normally do not need an explicit
# tests/CMakeLists.txt because the zephyr_subtree uses the test
# directories defined in the board's prj.conf.  However, since
# our custom Unity tests are packaged as a subdirectory we list it
# explicitly so that `west twister -s tests/xd58c` or
# `west twister -s tests` will pick it up.

add_subdirectory(xd58c)
